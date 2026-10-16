from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from PIL import Image

from officina.importazione import annulla, scansione
from officina.importazione.motore import Motore


def _foto(percorso: Path, colore=(10, 20, 30)) -> Path:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), colore).save(percorso, "JPEG")
    return percorso


def _nomi(trovati) -> list[str]:
    return sorted(p.name for p in trovati.file)


def _aggiungi(archivio, *cartelle: Path) -> list[int]:
    with archivio.scrittura() as connessione:
        return [scansione.aggiungi_cartella(connessione, c) for c in cartelle]


def test_la_cartella_con_lo_stesso_inizio_non_si_confonde(archivio, tmp_path):
    foto = tmp_path / "Foto"
    altra = tmp_path / "Foto 2019"
    foto.mkdir()
    altra.mkdir()
    primo, secondo = _aggiungi(archivio, foto, altra)
    with archivio.lettura() as connessione:
        assert scansione.cartella_di(connessione, altra / "IMG_1.jpg") == secondo
        assert scansione.cartella_di(connessione, foto / "IMG_1.jpg") == primo
        assert scansione.cartella_di(connessione, foto / "sotto" / "IMG_1.jpg") == primo
        assert scansione.cartella_di(connessione, tmp_path / "Fotografie" / "IMG_1.jpg") is None
        assert scansione.cartella_di(connessione, tmp_path / "Foto") == primo


def test_vince_la_cartella_piu_vicina_al_file(archivio, tmp_path):
    grande = tmp_path / "Foto"
    piccola = grande / "Mare"
    piccola.mkdir(parents=True)
    primo, secondo = _aggiungi(archivio, grande, piccola)
    with archivio.lettura() as connessione:
        assert scansione.cartella_di(connessione, piccola / "a.jpg") == secondo
        assert scansione.cartella_di(connessione, grande / "a.jpg") == primo
        assert scansione.cartella_di(connessione, grande / "Montagna" / "a.jpg") == primo


def test_annullare_una_cartella_non_porta_via_quella_con_lo_stesso_inizio(archivio, tmp_path):
    foto = tmp_path / "Foto"
    altra = tmp_path / "Foto 2019"
    _foto(foto / "a.jpg", (200, 10, 10))
    _foto(altra / "b.jpg", (10, 200, 10))
    _foto(altra / "c.jpg", (10, 10, 200))
    motore = Motore(archivio)
    motore.prepara([foto, altra])
    assert motore.esegui().stato == "finita"

    with archivio.lettura() as connessione:
        scatti_prima = connessione.execute("SELECT count(*) FROM scatti").fetchone()[0]
        assegnazioni = {Path(r["percorso"]).name: r["cartella_id"] for r in connessione.execute(
            "SELECT percorso, cartella_id FROM percorsi")}
    assert scatti_prima == 3
    assert assegnazioni["a.jpg"] != assegnazioni["b.jpg"] == assegnazioni["c.jpg"]

    with archivio.scrittura() as connessione:
        annulla.annulla(connessione, assegnazioni["a.jpg"])
    with archivio.lettura() as connessione:
        rimasti = {Path(r["percorso"]).name for r in connessione.execute("SELECT percorso FROM percorsi")}
        assert connessione.execute("SELECT count(*) FROM scatti").fetchone()[0] == 2
    assert rimasti == {"b.jpg", "c.jpg"}


def test_il_nome_scelto_dall_utente_puo_chiamarsi_officina(tmp_path):
    scelta = tmp_path / "Officina" / "Foto 2019"
    _foto(scelta / "a.jpg")
    _foto(scelta / "sotto" / "b.jpg", (1, 2, 3))
    assert _nomi(scansione.elenca([scelta])) == ["a.jpg", "b.jpg"]
    assert _nomi(scansione.elenca([tmp_path / "Officina"])) == ["a.jpg", "b.jpg"]


def test_le_cartelle_da_saltare_si_saltano_solo_dentro_quella_scelta(tmp_path):
    scelta = tmp_path / "Raccolta"
    _foto(scelta / "buona.jpg")
    _foto(scelta / "officina" / "interna.jpg", (1, 2, 3))
    _foto(scelta / "sotto" / ".git" / "oggetto.jpg", (4, 5, 6))
    _foto(scelta / "sotto" / "Officina" / "altro.jpg", (7, 8, 9))
    _foto(scelta / "sotto" / "giusta.jpg", (9, 9, 9))
    assert _nomi(scansione.elenca([scelta])) == ["buona.jpg", "giusta.jpg"]


def test_i_file_nascosti_e_le_estensioni_da_saltare_restano_come_prima(tmp_path):
    scelta = tmp_path / "Raccolta"
    _foto(scelta / "a.jpg")
    _foto(scelta / ".nascosto.jpg", (1, 2, 3))
    (scelta / "note.txt").write_text("ciao")
    (scelta / "vuoto.dat").write_bytes(b"")
    (scelta / "vuota.jpg").write_bytes(b"")
    trovati = scansione.elenca([scelta])
    assert _nomi(trovati) == ["a.jpg", "vuota.jpg"]
    assert trovati.saltati == 1


def test_i_file_escono_in_ordine_e_con_le_misure(tmp_path):
    scelta = tmp_path / "Raccolta"
    for nome in ("c.jpg", "a.jpg", "b/b.jpg"):
        _foto(scelta / nome, (len(nome), 0, 0))
    trovati = scansione.elenca([scelta])
    assert trovati.file == sorted(trovati.file)
    assert trovati.byte == sum(p.stat().st_size for p in trovati.file)
    assert all(trovati.dimensioni[str(p)] == p.stat().st_size for p in trovati.file)


def test_i_collegamenti_a_file_e_a_cartelle_non_si_seguono(tmp_path):
    fuori = tmp_path / "fuori"
    _foto(fuori / "estranea.jpg", (200, 0, 0))
    _foto(fuori / "altra" / "estranea_due.jpg", (0, 200, 0))
    scelta = tmp_path / "scelta"
    _foto(scelta / "mia.jpg")
    try:
        (scelta / "scorciatoia.jpg").symlink_to(fuori / "estranea.jpg")
        (scelta / "porta").symlink_to(fuori, target_is_directory=True)
    except OSError:
        pytest.skip("i collegamenti non si possono fare qui")
    trovati = scansione.elenca([scelta])
    assert _nomi(trovati) == ["mia.jpg"]
    assert trovati.collegamenti == 2


def test_un_collegamento_rotto_non_ferma_la_scansione(tmp_path):
    scelta = tmp_path / "scelta"
    _foto(scelta / "mia.jpg")
    try:
        (scelta / "rotto.jpg").symlink_to(tmp_path / "non_esiste.jpg")
    except OSError:
        pytest.skip("i collegamenti non si possono fare qui")
    assert _nomi(scansione.elenca([scelta])) == ["mia.jpg"]


def test_una_giunzione_di_windows_si_riconosce_dal_tipo_di_rimando():
    class Stato:
        def __init__(self, modo, attributi=0, tipo=0):
            self.st_mode = modo
            self.st_file_attributes = attributi
            self.st_reparse_tag = tipo

    cartella = stat.S_IFDIR | 0o755
    assert scansione.e_un_rimando(Stato(stat.S_IFLNK | 0o777))
    assert scansione.e_un_rimando(Stato(cartella, 0x410, 0xA0000003))
    assert scansione.e_un_rimando(Stato(cartella, 0x410, 0xA000000C))
    assert not scansione.e_un_rimando(Stato(cartella, 0x10))
    assert not scansione.e_un_rimando(Stato(stat.S_IFREG | 0o644, 0x400, 0x9000001A))
    assert not scansione.e_un_rimando(os.lstat(__file__))


def test_una_cartella_il_cui_vero_percorso_esce_dalla_scelta_si_lascia(tmp_path, monkeypatch):
    scelta = tmp_path / "scelta"
    _foto(scelta / "mia.jpg")
    _foto(scelta / "dentro" / "altra.jpg", (1, 2, 3))
    vero = os.path.realpath

    def dirotta(percorso, *argomenti, **parole):
        if Path(percorso).name == "dentro":
            return str(tmp_path / "altrove")
        return vero(percorso, *argomenti, **parole)

    monkeypatch.setattr(os.path, "realpath", dirotta)
    assert _nomi(scansione.elenca([scelta])) == ["mia.jpg"]


def test_una_cartella_che_non_c_e_si_dice(tmp_path):
    from officina.errori import CartellaNonTrovata

    with pytest.raises(CartellaNonTrovata):
        scansione.elenca([tmp_path / "manca"])
