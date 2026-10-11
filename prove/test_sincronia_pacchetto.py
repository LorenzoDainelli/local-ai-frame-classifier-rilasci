from __future__ import annotations


import pytest

from officina.archivio.database import adesso, inserisci
from officina.errori import ErroreOfficina
from officina.modello import cambiamenti, etichette, nodi
from officina.sincronia import costruzione, formato, lettore

PAROLA = "questa-e-una-password"


def _metti_una_foto(archivio, cartella, nome: str, contenuto: bytes) -> str:
    import hashlib

    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.write_bytes(contenuto)
    impronta = hashlib.blake2b(contenuto, digest_size=32).hexdigest()

    scatto_id = inserisci(
        connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?)", adesso())
    file_id = inserisci(
        connessione,
        "INSERT INTO file_media (impronta, dimensione, genere, formato, "
        "scatto_id, ruolo, aggiunto_il) "
        "VALUES (?, ?, 'immagine', 'jpeg', ?, 'principale', ?)",
        impronta, len(contenuto), scatto_id, adesso())
    inserisci(
        connessione,
        "INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
        "VALUES (?, ?, ?, ?)", file_id, str(sorgente), nome, adesso())
    return impronta


@pytest.fixture
def archivio_con_roba(archivio, tmp_path):
    connessione = archivio.connessione
    foto = tmp_path / "foto"
    foto.mkdir()
    prima = _metti_una_foto(archivio, foto, "una.jpg", b"il contenuto della prima" * 40)
    seconda = _metti_una_foto(archivio, foto, "due.jpg", b"e questo della seconda" * 40)

    vestiti = nodi.crea(connessione, "vestiti")
    magliette = nodi.crea(connessione, "magliette", vestiti)
    etichette.metti(connessione, 1, magliette, "si", "utente")
    etichette.metti(connessione, 2, magliette, "no", "utente")
    return archivio, tmp_path, prima, seconda, magliette


def test_un_pacchetto_si_scrive_e_si_rilegge(archivio_con_roba):
    archivio, tmp_path, prima, seconda, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)

    assert fatto.carta.completa
    assert fatto.carta.quanti_file == 2
    assert fatto.cartella.name.startswith("Officina-da-")

    with lettore.apri(fatto.cartella, PAROLA) as pacchetto:
        gesti = pacchetto.cambiamenti()
        assert [(g["cosa"], g["azione"]) for g in gesti] == [
            ("nodo", "creato"), ("nodo", "creato"),
            ("etichetta", "messa"), ("etichetta", "messa"),
        ]
        etichetta = gesti[2]
        assert etichetta["impronta"] == prima
        assert etichetta["sentiero"] == "vestiti › magliette"
        assert pacchetto.inventario() == {prima, seconda}


def test_l_originale_esce_identico_bit_per_bit(archivio_con_roba):
    archivio, tmp_path, prima, _, _ = archivio_con_roba
    originale = (tmp_path / "foto" / "una.jpg").read_bytes()
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)

    with lettore.apri(fatto.cartella, PAROLA) as pacchetto:
        riga = [f for f in pacchetto.file() if f["impronta"] == prima][0]
        uscito = tmp_path / "uscito.jpg"
        impronta = pacchetto.tira_fuori(riga["posto"], uscito)

    assert uscito.read_bytes() == originale
    assert impronta == prima


def test_la_carta_non_dice_niente_di_cosa_c_e_dentro(archivio_con_roba):
    archivio, tmp_path, _, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)
    testo = (fatto.cartella / formato.CARTA).read_text(encoding="utf-8")

    for parola in ("vestiti", "magliette", "una.jpg", str(tmp_path)):
        assert parola not in testo


def test_si_puo_sbirciare_senza_password(archivio_con_roba):
    archivio, tmp_path, _, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)
    carta = lettore.sbircia(fatto.cartella)
    assert carta.completa
    assert carta.quanti_cambiamenti == 4


def test_un_pacchetto_interrotto_non_si_apre(archivio_con_roba):
    archivio, tmp_path, _, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)
    carta = formato.Carta.leggi(fatto.cartella)
    carta.stato = formato.INTERROTTO
    carta.scrivi(fatto.cartella)

    with pytest.raises(ErroreOfficina) as guaio:
        with lettore.apri(fatto.cartella, PAROLA):
            pass
    assert guaio.value.codice == "pacchetto_interrotto"


def test_la_password_sbagliata_si_distingue_dal_pacchetto_rotto(archivio_con_roba):
    archivio, tmp_path, _, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)
    with pytest.raises(ErroreOfficina) as guaio:
        with lettore.apri(fatto.cartella, "un-altra-password"):
            pass
    assert guaio.value.codice != "pacchetto_interrotto"


def test_un_pacchetto_dell_archivio_sbagliato_si_ferma(archivio_con_roba):
    archivio, tmp_path, _, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)
    with pytest.raises(ErroreOfficina) as guaio:
        with lettore.apri(fatto.cartella, PAROLA, archivio_atteso="reale"):
            pass
    assert guaio.value.codice == "archivio_sbagliato"


def test_un_file_tagliato_non_si_apre(archivio_con_roba):
    archivio, tmp_path, prima, _, _ = archivio_con_roba
    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA)

    with lettore.apri(fatto.cartella, PAROLA) as pacchetto:
        riga = [f for f in pacchetto.file() if f["impronta"] == prima][0]
        posto = riga["posto"]
    dove = formato.dentro(fatto.cartella, posto)
    dove.write_bytes(dove.read_bytes()[:-20])

    with lettore.apri(fatto.cartella, PAROLA) as pacchetto:
        with pytest.raises(Exception):
            pacchetto.tira_fuori(posto, tmp_path / "rotto.jpg")


def test_un_percorso_che_esce_dalla_cartella_viene_rifiutato(tmp_path):
    with pytest.raises(ErroreOfficina) as guaio:
        formato.dentro(tmp_path, "../../fuori.txt")
    assert guaio.value.codice == "percorso_sospetto"


def test_il_secondo_pacchetto_non_rimanda_quello_che_c_e_gia(archivio_con_roba):
    archivio, tmp_path, prima, seconda, _ = archivio_con_roba
    connessione = archivio.connessione

    altra = cambiamenti.impara_dal_pacchetto(
        connessione, codice="a" * 32, nome="ZenBook", visto_di_me=3,
        inventario={prima})

    fatto = costruzione.costruisci(archivio, tmp_path / "fuori", PAROLA,
                                   per_macchina_id=altra)
    assert fatto.carta.quanti_file == 1
    assert fatto.carta.dal_seriale == 3
    assert fatto.carta.quanti_cambiamenti == 1

    with lettore.apri(fatto.cartella, PAROLA) as pacchetto:
        posti = {f["impronta"]: f["posto"] for f in pacchetto.file()}
    assert posti[prima] is None
    assert posti[seconda] is not None
