from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from officina import VERSIONE_SCHEMA
from officina.archivio import accesso, database, migrazioni
from officina.doppioni import motore as doppioni_motore
from officina.importazione import miniature
from officina.importazione.motore import Motore


def _foto(percorso: Path, colore=(10, 20, 30)) -> Path:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), colore).save(percorso, "JPEG")
    return percorso


def _conta(archivio, tabella: str) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(f"SELECT count(*) FROM {tabella}").fetchone()[0]


@pytest.mark.parametrize("guasto", [RuntimeError("si rompe"), MemoryError(), OverflowError("troppo")])
def test_una_miniatura_che_non_riesce_non_butta_via_il_file_gia_scritto(archivio, tmp_path, monkeypatch, guasto):
    cartella = tmp_path / "foto"
    _foto(cartella / "a.jpg")
    _foto(cartella / "b.jpg", (200, 100, 50))

    def si_rompe(*_, **__):
        raise guasto

    monkeypatch.setattr(miniature, "per_file", si_rompe)
    motore = Motore(archivio)
    motore.prepara([cartella])
    avanzamento = motore.esegui()

    assert avanzamento.stato == "finita"
    assert avanzamento.fatti == 2 and avanzamento.saltati == 0
    assert _conta(archivio, "scatti") == 2
    assert _conta(archivio, "file_media") == 2
    assert _conta(archivio, "non_importati") == 0
    with archivio.lettura() as connessione:
        assert connessione.execute(
            "SELECT count(*) FROM coda_importazione WHERE stato = 'fatto'").fetchone()[0] == 2
        assert connessione.execute(
            "SELECT count(*) FROM file_media WHERE miniatura IS NULL").fetchone()[0] == 2


def test_la_miniatura_mancante_si_rifa_dopo(archivio, tmp_path, monkeypatch):
    cartella = tmp_path / "foto"
    _foto(cartella / "a.jpg")
    vera = miniature.per_file

    def si_rompe(*_, **__):
        raise RuntimeError("no")

    monkeypatch.setattr(miniature, "per_file", si_rompe)
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    monkeypatch.setattr(miniature, "per_file", vera)
    assert miniature.rigenera_mancanti(archivio) == 1
    with archivio.lettura() as connessione:
        assert connessione.execute(
            "SELECT count(*) FROM file_media WHERE miniatura IS NOT NULL").fetchone()[0] == 1


def test_un_guasto_imprevisto_nell_impronta_dell_occhio_non_butta_via_il_file(archivio, tmp_path, monkeypatch):
    from officina.doppioni import occhio

    cartella = tmp_path / "foto"
    _foto(cartella / "a.jpg")

    def si_rompe(*_, **__):
        raise Image.DecompressionBombError("troppi punti")

    monkeypatch.setattr(occhio, "del_percorso", si_rompe)
    motore = Motore(archivio)
    motore.prepara([cartella])
    assert motore.esegui().stato == "finita"
    assert _conta(archivio, "scatti") == 1
    assert _conta(archivio, "non_importati") == 0
    with archivio.lettura() as connessione:
        segno = connessione.execute("SELECT impronta_occhio FROM file_media").fetchone()[0]
    assert segno == doppioni_motore.NON_SI_E_POTUTA


def test_un_file_che_non_si_apre_resta_tra_i_non_importati(archivio, tmp_path):
    cartella = tmp_path / "foto"
    _foto(cartella / "a.jpg")
    (cartella / "finta.jpg").write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 1 1\n")
    motore = Motore(archivio)
    motore.prepara([cartella])
    avanzamento = motore.esegui()
    assert avanzamento.fatti == 1 and avanzamento.saltati == 1
    assert _conta(archivio, "scatti") == 1
    with archivio.lettura() as connessione:
        riga = connessione.execute("SELECT percorso, motivo FROM non_importati").fetchone()
    assert Path(riga["percorso"]).name == "finta.jpg"
    assert riga["motivo"] == "estensione_bugiarda"


def test_la_preparazione_non_conta_i_collegamenti(archivio, tmp_path):
    cartella = tmp_path / "foto"
    _foto(cartella / "a.jpg")
    try:
        (cartella / "b.jpg").symlink_to(cartella / "a.jpg")
    except OSError:
        pytest.skip("i collegamenti non si possono fare qui")
    motore = Motore(archivio)
    assert motore.prepara([cartella])["file"] == 1


def _inserisci_cartella(connessione, numero: int, percorso: str, attiva: int = 1) -> None:
    connessione.execute(
        "INSERT INTO cartelle_sorgente (id, percorso, aggiunta_il, attiva) VALUES (?, ?, 'x', ?)",
        (numero, percorso, attiva))


def _inserisci_file(connessione, numero: int, percorso: str, cartella_id: int | None) -> None:
    connessione.execute(
        "INSERT INTO file_media (id, impronta, dimensione, genere, aggiunto_il) "
        "VALUES (?, ?, 1, 'immagine', 'x')", (numero, f"{numero:064d}"))
    connessione.execute(
        "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, visto_il) "
        "VALUES (?, ?, ?, 'n', 'x')", (numero, cartella_id, percorso))


def _cartella_di(connessione, numero: int):
    return connessione.execute(
        "SELECT cartella_id FROM percorsi WHERE file_id = ?", (numero,)).fetchone()[0]


def test_l_ultima_migrazione_e_la_versione_la_conosce():
    assert migrazioni.MIGRAZIONI[-1].versione == VERSIONE_SCHEMA
    assert [m.versione for m in migrazioni.MIGRAZIONI] == list(range(1, VERSIONE_SCHEMA + 1))


def test_la_migrazione_toglie_le_coordinate_fuori_dal_mondo(archivio):
    infinito = float("inf")
    with archivio.scrittura() as connessione:
        for numero, (lat, lon) in enumerate((
                (45.0, 9.0), (infinito, 9.0), (-infinito, 9.0), (45.0, infinito),
                (91.0, 9.0), (45.0, -181.0), (-90.0, 180.0), (None, None)), start=1):
            connessione.execute(
                "INSERT INTO scatti (id, genere, origine_data, giorno, latitudine, longitudine, "
                "creato_il) VALUES (?, 'foto', 'exif', '2020-01-01', ?, ?, 'x')",
                (numero, lat, lon))
            connessione.execute(
                "INSERT INTO file_media (id, impronta, dimensione, genere, latitudine, longitudine, "
                "aggiunto_il) VALUES (?, ?, 1, 'immagine', ?, ?, 'x')",
                (numero, f"{numero:064d}", lat, lon))
        migrazioni._versione_53(connessione)
    with archivio.lettura() as connessione:
        for tabella in ("scatti", "file_media"):
            righe = {r["id"]: (r["latitudine"], r["longitudine"]) for r in connessione.execute(
                f"SELECT id, latitudine, longitudine FROM {tabella}")}
            assert righe[1] == (45.0, 9.0)
            assert righe[7] == (-90.0, 180.0)
            for numero in (2, 3, 4, 5, 6):
                assert righe[numero] == (None, None), (tabella, numero)
            assert righe[8] == (None, None)


def test_la_migrazione_aggiusta_i_luoghi_dal_centro_infinito(archivio):
    infinito = float("inf")
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO luoghi (id, nome, centro_lat, centro_lon, raggio_metri, quanti, nato_il) "
            "VALUES (1, 'Casa', ?, 9.0, 5, 2, 'x')", (infinito,))
        connessione.execute(
            "INSERT INTO luoghi (id, nome, centro_lat, centro_lon, raggio_metri, quanti, nato_il) "
            "VALUES (2, 'Vuoto', ?, 9.0, 5, 1, 'x')", (infinito,))
        connessione.execute(
            "INSERT INTO luoghi (id, nome, centro_lat, centro_lon, raggio_metri, quanti, nato_il) "
            "VALUES (3, 'Buono', 10.0, 10.0, 5, 1, 'x')")
        for numero, (lat, luogo) in enumerate(
                ((40.0, 1), (infinito, 1), (infinito, 2), (10.0, 3)), start=1):
            connessione.execute(
                "INSERT INTO scatti (id, genere, origine_data, giorno, latitudine, longitudine, "
                "luogo_id, creato_il) VALUES (?, 'foto', 'exif', '2020-01-01', ?, 9.0, ?, 'x')",
                (numero, lat, luogo))
        migrazioni._versione_53(connessione)
    with archivio.lettura() as connessione:
        casa = connessione.execute("SELECT * FROM luoghi WHERE id = 1").fetchone()
        assert (casa["centro_lat"], casa["centro_lon"], casa["quanti"]) == (40.0, 9.0, 1)
        assert casa["nome"] == "Casa"
        assert connessione.execute("SELECT count(*) FROM luoghi WHERE id = 2").fetchone()[0] == 0
        assert connessione.execute("SELECT count(*) FROM luoghi WHERE id = 3").fetchone()[0] == 1
        assert connessione.execute("SELECT luogo_id FROM scatti WHERE id = 3").fetchone()[0] is None
        assert connessione.execute("SELECT luogo_id FROM scatti WHERE id = 4").fetchone()[0] == 3


def test_la_migrazione_riporta_ogni_percorso_alla_sua_cartella(archivio):
    with archivio.scrittura() as connessione:
        _inserisci_cartella(connessione, 1, "/dischi/Foto")
        _inserisci_cartella(connessione, 2, "/dischi/Foto 2019")
        _inserisci_cartella(connessione, 3, "/dischi/Foto/Mare", attiva=0)
        _inserisci_cartella(connessione, 4, "D:\\Archivio")
        _inserisci_cartella(connessione, 5, "D:\\Archivio 2")
        _inserisci_file(connessione, 1, "/dischi/Foto/a.jpg", 1)
        _inserisci_file(connessione, 2, "/dischi/Foto 2019/b.jpg", 1)
        _inserisci_file(connessione, 3, "/dischi/Foto/Mare/c.jpg", 1)
        _inserisci_file(connessione, 4, "/dischi/Fotografie/d.jpg", 1)
        _inserisci_file(connessione, 5, "D:\\Archivio 2\\e.jpg", 4)
        _inserisci_file(connessione, 6, "d:\\archivio\\f.jpg", 5)
        _inserisci_file(connessione, 7, "/dischi/Foto 2019/g.jpg", None)
        _inserisci_file(connessione, 8, "/dischi/Foto 2019/h.jpg", 2)
        migrazioni._versione_53(connessione)
    with archivio.lettura() as connessione:
        assert _cartella_di(connessione, 1) == 1
        assert _cartella_di(connessione, 2) == 2
        assert _cartella_di(connessione, 3) == 3
        assert _cartella_di(connessione, 4) is None
        assert _cartella_di(connessione, 5) == 5
        assert _cartella_di(connessione, 6) == 4
        assert _cartella_di(connessione, 7) is None
        assert _cartella_di(connessione, 8) == 2


def test_rifare_la_migrazione_non_cambia_piu_niente(archivio):
    with archivio.scrittura() as connessione:
        _inserisci_cartella(connessione, 1, "/dischi/Foto")
        _inserisci_file(connessione, 1, "/dischi/Foto 2019/b.jpg", 1)
        _inserisci_file(connessione, 2, "/dischi/Foto/b.jpg", 1)
        migrazioni._versione_53(connessione)
        prima = [tuple(r) for r in connessione.execute("SELECT id, cartella_id FROM percorsi ORDER BY id")]
        migrazioni._versione_53(connessione)
        dopo = [tuple(r) for r in connessione.execute("SELECT id, cartella_id FROM percorsi ORDER BY id")]
    assert prima == dopo == [(1, None), (2, 1)]


def test_un_archivio_alla_versione_52_arriva_alla_53_da_solo(tmp_path, monkeypatch):
    from officina.impostazioni import posizione

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    dove = posizione("finto")
    dove.database.parent.mkdir(parents=True, exist_ok=True)
    connessione = database.connetti(dove.database)
    database.crea_da_zero(connessione)
    connessione.execute("PRAGMA user_version = 1")
    for migrazione in migrazioni.MIGRAZIONI:
        if 2 <= migrazione.versione <= 52:
            migrazione.applica(connessione)
    connessione.execute("PRAGMA user_version = 52")
    connessione.execute(
        "INSERT INTO scatti (id, genere, origine_data, giorno, latitudine, longitudine, creato_il) "
        "VALUES (1, 'foto', 'exif', '2020-01-01', ?, 9.0, 'x')", (float("inf"),))
    connessione.execute(
        "INSERT INTO cartelle_sorgente (id, percorso, aggiunta_il) VALUES (1, '/dischi/Foto', 'x')")
    connessione.execute(
        "INSERT INTO file_media (id, impronta, dimensione, genere, aggiunto_il) "
        "VALUES (1, ?, 1, 'immagine', 'x')", ("a" * 64,))
    connessione.execute(
        "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, visto_il) "
        "VALUES (1, 1, '/dischi/Foto 2019/x.jpg', 'x.jpg', 'x')")
    connessione.commit()
    connessione.close()

    aperto = accesso.apri("finto")
    try:
        assert migrazioni.versione_attuale(aperto.connessione) == VERSIONE_SCHEMA
        assert aperto.connessione.execute(
            "SELECT latitudine FROM scatti WHERE id = 1").fetchone()[0] is None
        assert aperto.connessione.execute(
            "SELECT cartella_id FROM percorsi WHERE file_id = 1").fetchone()[0] is None
    finally:
        accesso.chiudi(con_copia=False)
