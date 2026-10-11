from __future__ import annotations

import hashlib

import pytest

from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.impostazioni import Posizione
from officina.modello import persone, telefoni
from officina.sincronia import costruzione, fusione

PAROLA = "questa-e-una-password"


def _foto(archivio, cartella, nome: str, contenuto: bytes) -> tuple[int, str]:
    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.parent.mkdir(parents=True, exist_ok=True)
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
    return scatto_id, impronta


def _volto(archivio, scatto_id: int, persona_id: int) -> int:
    return inserisci(
        archivio.connessione,
        "INSERT INTO volti (scatto_id, riquadro, area, nitidezza, sicurezza, "
        "modello, versione, persona_id, trovato_il) "
        "VALUES (?, '[0,0,1,1]', 0.5, 0.5, 0.9, 'finto', '1', ?, ?)",
        scatto_id, persona_id, adesso())


def _scatto_di(archivio, impronta: str) -> int:
    riga = uno(archivio.connessione,
               "SELECT scatto_id FROM file_media WHERE impronta = ?", impronta)
    assert riga is not None
    return riga["scatto_id"]


@pytest.fixture
def due_pc(archivio, tmp_path):
    altro = Archivio(Posizione(tmp_path / "zenbook", "finto")).apri()
    try:
        yield archivio, altro, tmp_path
    finally:
        altro.chiudi(con_copia=False)


def _travaso(mittente, destinatario, tmp_path, quale="scambio"):
    fatto = costruzione.costruisci(mittente, tmp_path / quale, PAROLA)
    return fusione.fondi(destinatario, fatto.cartella, PAROLA)


def _stessa_foto(fisso, zen, tmp_path, nome: str, contenuto: bytes):
    qui = _foto(fisso, tmp_path / "foto", nome, contenuto)
    la = _foto(zen, tmp_path / "foto-zen", nome, contenuto)
    return qui, la


def test_il_nome_dato_di_la_arriva_al_mucchio_giusto_di_qua(due_pc):
    fisso, zen, tmp_path = due_pc
    (qui, _), (la, _) = _stessa_foto(fisso, zen, tmp_path, "anna.jpg",
                                     b"la faccia di anna" * 40)
    anna = persone.crea(fisso.connessione, "Anna")
    _volto(fisso, qui, anna)
    senza_nome = persone.crea(zen.connessione)
    _volto(zen, la, senza_nome)

    esito = _travaso(fisso, zen, tmp_path)

    assert esito.persone_nominate == 1
    riga = uno(zen.connessione, "SELECT nome FROM persone WHERE id = ?",
               senza_nome)
    assert riga["nome"] == "Anna"


def test_una_persona_divisa_in_due_finisce_nel_cassetto_e_non_si_fonde(due_pc):
    fisso, zen, tmp_path = due_pc
    (uno_qui, _), (uno_la, _) = _stessa_foto(fisso, zen, tmp_path, "a.jpg",
                                             b"anna di fronte" * 40)
    (due_qui, _), (due_la, _) = _stessa_foto(fisso, zen, tmp_path, "b.jpg",
                                             b"anna di profilo" * 40)
    anna = persone.crea(fisso.connessione, "Anna")
    _volto(fisso, uno_qui, anna)
    _volto(fisso, due_qui, anna)

    primo = persone.crea(zen.connessione)
    secondo = persone.crea(zen.connessione)
    _volto(zen, uno_la, primo)
    _volto(zen, due_la, secondo)

    esito = _travaso(fisso, zen, tmp_path)

    assert esito.persone_da_guardare == 1
    assert esito.persone_nominate == 0
    coppie = persone.cassetto(zen.connessione)
    assert len(coppie) == 1
    assert {coppie[0]["una_id"], coppie[0]["altra_id"]} == {primo, secondo}
    nomi = [r["nome"] for r in tutti(zen.connessione, "SELECT nome FROM persone")]
    assert nomi == [None, None]
    assert esito.note, "una cosa così va detta, non contata e basta"


def test_un_nome_che_hai_gia_dato_di_qua_non_si_tocca(due_pc):
    fisso, zen, tmp_path = due_pc
    (qui, _), (la, _) = _stessa_foto(fisso, zen, tmp_path, "chi.jpg",
                                     b"la stessa faccia" * 40)
    _volto(fisso, qui, persone.crea(fisso.connessione, "Anna"))
    mia = persone.crea(zen.connessione, "Annarella")
    _volto(zen, la, mia)

    _travaso(fisso, zen, tmp_path)

    riga = uno(zen.connessione, "SELECT nome FROM persone WHERE id = ?", mia)
    assert riga["nome"] == "Annarella"


def test_se_qui_i_volti_non_sono_stati_cercati_lo_dice(due_pc):
    fisso, zen, tmp_path = due_pc
    (qui, _), _ = _stessa_foto(fisso, zen, tmp_path, "a.jpg", b"una faccia" * 40)
    _volto(fisso, qui, persone.crea(fisso.connessione, "Anna"))

    esito = _travaso(fisso, zen, tmp_path)

    assert esito.persone_nominate == 0
    assert any("volti" in nota for nota in esito.note)


def test_una_persona_messa_a_mano_arriva_davvero(due_pc):
    fisso, zen, tmp_path = due_pc
    (di_fronte_qui, _), (di_fronte_la, _) = _stessa_foto(
        fisso, zen, tmp_path, "fronte.jpg", b"anna di fronte" * 40)
    (spalle_qui, _), (spalle_la, _) = _stessa_foto(
        fisso, zen, tmp_path, "spalle.jpg", b"anna di spalle" * 40)
    anna = persone.crea(fisso.connessione, "Anna")
    _volto(fisso, di_fronte_qui, anna)
    persone.metti_a_mano(fisso.connessione, spalle_qui, anna)

    suo = persone.crea(zen.connessione)
    _volto(zen, di_fronte_la, suo)

    _travaso(fisso, zen, tmp_path)

    riga = uno(zen.connessione,
               "SELECT id FROM persone_negli_scatti WHERE scatto_id = ? "
               "AND persona_id = ?", spalle_la, suo)
    assert riga is not None, "la persona detta da te doveva arrivare"


def test_le_persone_arrivano_due_volte_senza_raddoppiare(due_pc):
    fisso, zen, tmp_path = due_pc
    (qui, _), (la, _) = _stessa_foto(fisso, zen, tmp_path, "a.jpg",
                                     b"una faccia" * 40)
    _volto(fisso, qui, persone.crea(fisso.connessione, "Anna"))
    _volto(zen, la, persone.crea(zen.connessione))

    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)
    fusione.fondi(zen, fatto.cartella, PAROLA)
    di_nuovo = fusione.fondi(zen, fatto.cartella, PAROLA)

    assert di_nuovo.persone_nominate == 0
    quante = tutti(zen.connessione, "SELECT id FROM persone")
    assert len(quante) == 1


def test_un_cuore_arriva_col_nome_del_telefono_attaccato(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "cuore.jpg", b"la preferita" * 40)
    redmi = telefoni.crea(fisso.connessione, "Redmi", "android")
    inserisci(fisso.connessione,
              "INSERT INTO cuori (telefono_id, impronta, scatto_id, messo_il, "
              "tornato_il) VALUES (?, ?, ?, ?, ?)",
              redmi, impronta, _scatto_di(fisso, impronta),
              "2026-05-05T10:00:00Z", adesso())

    esito = _travaso(fisso, zen, tmp_path)

    assert esito.cuori_arrivati == 1
    assert esito.telefoni_nuovi == 1
    la = telefoni.per_nome(zen.connessione, "Redmi")
    assert la is not None and la["sistema"] == "android"
    riga = uno(zen.connessione,
               "SELECT * FROM cuori WHERE telefono_id = ?", la["id"])
    assert riga["impronta"] == impronta
    assert riga["messo_il"] == "2026-05-05T10:00:00Z"
    assert riga["scatto_id"] == _scatto_di(zen, impronta)


def test_due_telefoni_diversi_restano_due(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "a.jpg", b"la stessa foto" * 40)
    redmi = telefoni.crea(fisso.connessione, "Redmi", "android")
    inserisci(fisso.connessione,
              "INSERT INTO cuori (telefono_id, impronta, tornato_il) "
              "VALUES (?, ?, ?)", redmi, impronta, adesso())
    telefoni.crea(zen.connessione, "iPhone", "ios")

    _travaso(fisso, zen, tmp_path)

    nomi = sorted(r["nome"] for r in telefoni.elenco(zen.connessione))
    assert nomi == ["Redmi", "iPhone"] or nomi == ["iPhone", "Redmi"]
    assert len(nomi) == 2


def test_lo_stesso_cuore_due_volte_resta_uno(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "a.jpg", b"la preferita" * 40)
    redmi = telefoni.crea(fisso.connessione, "Redmi", "android")
    inserisci(fisso.connessione,
              "INSERT INTO cuori (telefono_id, impronta, tornato_il) "
              "VALUES (?, ?, ?)", redmi, impronta, adesso())

    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)
    fusione.fondi(zen, fatto.cartella, PAROLA)
    di_nuovo = fusione.fondi(zen, fatto.cartella, PAROLA)

    assert di_nuovo.cuori_arrivati == 0
    assert len(tutti(zen.connessione, "SELECT id FROM cuori")) == 1
