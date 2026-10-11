from __future__ import annotations

import hashlib
from pathlib import Path

from officina.immagini import consegna, lettura
from officina.importazione import miniature
from officina.importazione.motore import Motore


def _fotografia_della_cartella(cartella: Path) -> dict[str, tuple[str, int, float]]:
    stato = {}
    for percorso in sorted(cartella.rglob("*")):
        if percorso.is_file():
            dati = percorso.read_bytes()
            informazioni = percorso.stat()
            stato[str(percorso)] = (
                hashlib.blake2b(dati, digest_size=16).hexdigest(),
                informazioni.st_size,
                informazioni.st_mtime,
            )
    return stato


def test_importare_non_tocca_un_solo_byte(archivio, cartella_foto):
    prima = _fotografia_della_cartella(cartella_foto)

    motore = Motore(archivio)
    motore.prepara([cartella_foto])
    motore.esegui()

    dopo = _fotografia_della_cartella(cartella_foto)
    assert prima == dopo, "l'importazione ha modificato, spostato o toccato un originale"


def test_guardare_una_foto_non_la_tocca(archivio_pieno, cartella_foto):
    foto = sorted(cartella_foto.rglob("*.HEIC")) or sorted(cartella_foto.rglob("*.JPG"))
    assert foto, "l'archivio finto non ha prodotto nessuna foto"
    prima = _fotografia_della_cartella(cartella_foto)

    for percorso in foto[:3]:
        lettura.copia_di_lavoro(percorso, 400)
        consegna.per_browser(percorso, 400)
        miniature.fai(archivio_pieno, "impronta-di-prova", percorso, "immagine", 200)

    assert _fotografia_della_cartella(cartella_foto) == prima


def test_le_miniature_stanno_fuori_dalle_cartelle_delle_foto(archivio_pieno, cartella_foto):
    dentro = [p for p in cartella_foto.rglob("*")
              if p.is_file() and p.suffix.lower() in (".avif", ".webp")]
    assert dentro == []
    quante, _ = archivio_pieno.peso_miniature()
    assert quante > 0, "le miniature non sono state fatte da nessuna parte"


def test_calcolare_le_impronte_non_tocca_un_solo_byte(archivio_pieno, cartella_foto):
    from officina.impronte.motore import Passata

    prima = _fotografia_della_cartella(cartella_foto)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=4).esegui()
    dopo = _fotografia_della_cartella(cartella_foto)
    assert prima == dopo, "il calcolo delle impronte ha toccato un originale"


def test_le_impronte_stanno_nell_archivio_non_accanto_alle_foto(archivio_misurabile,
                                                                cartella_foto_grande):
    from officina.finto.generatore import TEMI_FINTI

    nuovi = [p for p in cartella_foto_grande.rglob("*")
             if p.is_file() and p.name != TEMI_FINTI
             and p.suffix.lower() not in (".heic", ".jpg", ".jpeg", ".png", ".mov")]
    assert nuovi == [], f"il programma ha lasciato dei file fra le foto: {nuovi}"
    with archivio_misurabile.lettura() as connessione:
        quante = connessione.execute("SELECT count(*) AS q FROM impronte").fetchone()["q"]
    assert quante > 0, "le impronte non sono state scritte da nessuna parte"
