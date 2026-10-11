from __future__ import annotations

from pathlib import Path

from PIL import Image

from officina.importazione import rileggi_macchine
from officina.web import etichettatura


def _foto(dove: Path, marca: str | None = None, modello: str | None = None) -> None:
    dove.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if marca:
        exif[0x010F] = marca
    if modello:
        exif[0x0110] = modello
    Image.new("RGB", (64, 48), (40, 120, 200)).save(dove, exif=exif)


def _importa(archivio, cartella: Path) -> None:
    from officina.importazione.motore import Motore

    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()


def _macchine(archivio) -> dict:
    with archivio.lettura() as connessione:
        return {Path(r["percorso"]).name: (r["marca"], r["modello"]) for r in connessione.execute(
            "SELECT p.percorso, f.marca, f.modello FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id")}


def test_all_importazione_la_macchina_si_salva(archivio, tmp_path):
    _foto(tmp_path / "foto" / "finta.jpg", "Apple", "iPhone 13")
    _importa(archivio, tmp_path / "foto")
    assert _macchine(archivio)["finta.jpg"] == ("Apple", "iPhone 13")


def test_le_macchine_dei_file_gia_in_archivio_si_rileggono(archivio, tmp_path):
    _foto(tmp_path / "foto" / "con.jpg", "Canon", "Canon EOS 80D")
    _foto(tmp_path / "foto" / "senza.jpg")
    _importa(archivio, tmp_path / "foto")
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET marca = NULL, modello = NULL")
        massimo = connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]
    archivio.salva_stato(rileggi_macchine.FINO_A, massimo)
    assert rileggi_macchine.quanti_restano(archivio) == 2

    assert rileggi_macchine.tutti_i_file(archivio) == 1

    macchine = _macchine(archivio)
    assert macchine["con.jpg"] == ("Canon", "Canon EOS 80D")
    assert macchine["senza.jpg"] == (None, None)
    assert archivio.stato(rileggi_macchine.FINO_A) is None


def test_il_nome_della_macchina_non_ripete_la_marca():
    assert etichettatura._macchina({"marca": "Canon", "modello": "Canon EOS 80D"}) == "Canon EOS 80D"
    assert etichettatura._macchina({"marca": "Apple", "modello": "iPhone 13"}) == "Apple iPhone 13"
    assert etichettatura._macchina({"marca": None, "modello": None}) is None
