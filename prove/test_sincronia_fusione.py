from __future__ import annotations

import hashlib

import pytest

from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, inserisci, uno
from officina.errori import ErroreOfficina
from officina.impostazioni import Posizione
from officina.modello import cambiamenti, etichette, nodi
from officina.sincronia import costruzione, formato, fusione

PAROLA = "questa-e-una-password"


def _foto(archivio, cartella, nome: str, contenuto: bytes) -> str:
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
    return impronta


@pytest.fixture
def due_pc(archivio, tmp_path):
    altro = Archivio(Posizione(tmp_path / "zenbook", "finto")).apri()
    try:
        yield archivio, altro, tmp_path
    finally:
        altro.chiudi(con_copia=False)


def _travaso(mittente, destinatario, tmp_path, nome_cartella="scambio"):
    fatto = costruzione.costruisci(mittente, tmp_path / nome_cartella, PAROLA)
    return fusione.fondi(destinatario, fatto.cartella, PAROLA), fatto


def test_una_etichetta_fatta_di_la_arriva_di_qua(due_pc):
    fisso, zen, tmp_path = due_pc
    impronta = _foto(fisso, tmp_path / "foto", "una.jpg", b"il contenuto" * 50)
    vestiti = nodi.crea(fisso.connessione, "vestiti")
    magliette = nodi.crea(fisso.connessione, "magliette", vestiti)
    etichette.metti(fisso.connessione, 1, magliette, "si", "utente")

    esito, _ = _travaso(fisso, zen, tmp_path)

    assert esito.file_nuovi == 1
    assert esito.originali_copiati == 1
    la = fusione.nodo_al_sentiero(zen.connessione, "vestiti › magliette")
    assert la is not None
    scatto = uno(zen.connessione,
                 "SELECT scatto_id FROM file_media WHERE impronta = ?", impronta)
    assert etichette.stato_di(zen.connessione, scatto["scatto_id"], la) == "si"
    percorso = uno(zen.connessione,
                   "SELECT p.percorso FROM percorsi p JOIN file_media f "
                   "ON f.id = p.file_id WHERE f.impronta = ?", impronta)
    from pathlib import Path
    assert Path(percorso["percorso"]).read_bytes() == b"il contenuto" * 50


def test_lo_stesso_pacchetto_letto_due_volte_non_fa_niente(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    nodo = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, 1, nodo, "si", "utente")

    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)
    primo = fusione.fondi(zen, fatto.cartella, PAROLA)
    secondo = fusione.fondi(zen, fatto.cartella, PAROLA)

    assert primo.gesti_applicati == 2
    assert secondo.gesti_applicati == 0
    assert secondo.gesti_gia_visti == 2
    assert not secondo.qualcosa_e_cambiato
    quanti = uno(zen.connessione, "SELECT count(*) AS c FROM nodi WHERE nome = 'mare'")
    assert quanti["c"] == 1


def test_lo_stesso_nodo_creato_sui_due_pc_resta_uno(due_pc):
    fisso, zen, tmp_path = due_pc
    prima = _foto(fisso, tmp_path / "foto", "una.jpg", b"la prima" * 50)
    qua = nodi.crea(fisso.connessione, "vacanze 2026")
    etichette.metti(fisso.connessione, 1, qua, "si", "utente")

    seconda = _foto(zen, tmp_path / "foto-zen", "due.jpg", b"la seconda" * 50)
    la = nodi.crea(zen.connessione, "vacanze 2026")
    etichette.metti(zen.connessione, 1, la, "si", "utente")

    _travaso(fisso, zen, tmp_path)

    nodi_cosi_chiamati = uno(
        zen.connessione,
        "SELECT count(*) AS c FROM nodi WHERE nome = 'vacanze 2026'")
    assert nodi_cosi_chiamati["c"] == 1
    dentro = uno(zen.connessione,
                 "SELECT count(*) AS c FROM etichette WHERE nodo_id = ?", la)
    assert dentro["c"] == 2
    assert prima != seconda


def test_due_omonimi_sotto_rami_diversi_restano_due(due_pc):
    fisso, zen, tmp_path = due_pc
    persone = nodi.crea(fisso.connessione, "persone")
    nodi.crea(fisso.connessione, "nonna", persone)
    luoghi = nodi.crea(fisso.connessione, "luoghi")
    nodi.crea(fisso.connessione, "nonna", luoghi)

    _travaso(fisso, zen, tmp_path)

    quante = uno(zen.connessione, "SELECT count(*) AS c FROM nodi WHERE nome = 'nonna'")
    assert quante["c"] == 2


def test_un_nodo_rinominato_di_la_non_diventa_un_secondo_nodo_di_qua(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    magliette = nodi.crea(fisso.connessione, "magliette")
    etichette.metti(fisso.connessione, 1, magliette, "si", "utente")
    _travaso(fisso, zen, tmp_path, "primo")

    nodi.rinomina(fisso.connessione, magliette, "magliette estive")
    _travaso(fisso, zen, tmp_path, "secondo")

    nomi = [r["nome"] for r in zen.connessione.execute(
        "SELECT nome FROM nodi ORDER BY nome")]
    assert nomi == ["magliette estive"]
    quante = uno(zen.connessione, "SELECT count(*) AS c FROM etichette")
    assert quante["c"] == 1


def test_un_nodo_spostato_di_la_si_sposta_di_qua(due_pc):
    fisso, zen, tmp_path = due_pc
    vestiti = nodi.crea(fisso.connessione, "vestiti")
    estate = nodi.crea(fisso.connessione, "estate")
    magliette = nodi.crea(fisso.connessione, "magliette", vestiti)
    _travaso(fisso, zen, tmp_path, "primo")

    nodi.sposta(fisso.connessione, magliette, estate)
    _travaso(fisso, zen, tmp_path, "secondo")

    assert fusione.nodo_al_sentiero(zen.connessione, "estate › magliette") is not None
    assert fusione.nodo_al_sentiero(zen.connessione, "vestiti › magliette") is None


def test_fra_due_decisioni_tue_vince_la_piu_recente(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, 1, mare, "si", "utente")
    _travaso(fisso, zen, tmp_path, "primo")

    scatto_la = uno(zen.connessione, "SELECT id FROM scatti")["id"]
    nodo_la = fusione.nodo_al_sentiero(zen.connessione, "mare")
    zen.connessione.execute(
        "UPDATE etichette SET stato = 'no', creata_il = '2020-01-01T00:00:00Z' "
        "WHERE scatto_id = ? AND nodo_id = ?", (scatto_la, nodo_la))

    etichette.metti(fisso.connessione, 1, mare, "no", "utente")
    esito, _ = _travaso(fisso, zen, tmp_path, "secondo")

    assert etichette.stato_di(zen.connessione, scatto_la, nodo_la) == "no"
    assert esito.etichette_perse == 0


def test_una_decisione_tua_vecchia_batte_una_della_macchina_nuova(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, 1, mare, "si", "utente")
    _travaso(fisso, zen, tmp_path, "primo")

    scatto_la = uno(zen.connessione, "SELECT id FROM scatti")["id"]
    nodo_la = fusione.nodo_al_sentiero(zen.connessione, "mare")
    zen.connessione.execute(
        "DELETE FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
        (scatto_la, nodo_la))
    etichette.metti(zen.connessione, scatto_la, nodo_la, "no", "sistema")

    fisso.connessione.execute(
        "UPDATE cambiamenti SET avvenuto_il = '2020-01-01T00:00:00Z'")
    fisso.connessione.execute(
        "UPDATE macchine SET mi_ha_vista_fino_a = 0 WHERE questa = 1")
    zen.connessione.execute("UPDATE macchine SET visto_fino_a = 0 WHERE questa = 0")

    _travaso(fisso, zen, tmp_path, "secondo")

    riga = uno(zen.connessione, "SELECT stato, origine FROM etichette "
               "WHERE scatto_id = ? AND nodo_id = ?", scatto_la, nodo_la)
    assert riga["stato"] == "si"
    assert riga["origine"] == "utente"


def test_la_tua_decisione_piu_recente_qui_non_si_lascia_scavalcare(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, 1, mare, "si", "utente")
    fisso.connessione.execute(
        "UPDATE cambiamenti SET avvenuto_il = '2020-01-01T00:00:00Z' "
        "WHERE cosa = 'etichetta'")

    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)
    scatto_la = inserisci(
        zen.connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?)", adesso())
    inserisci(zen.connessione,
              "INSERT INTO file_media (impronta, dimensione, genere, scatto_id, "
              "ruolo, aggiunto_il) VALUES (?, 1, 'immagine', ?, 'principale', ?)",
              hashlib.blake2b(b"contenuto" * 50, digest_size=32).hexdigest(),
              scatto_la, adesso())
    mare_la = nodi.crea(zen.connessione, "mare")
    etichette.metti(zen.connessione, scatto_la, mare_la, "no", "utente")

    esito = fusione.fondi(zen, fatto.cartella, PAROLA)

    assert etichette.stato_di(zen.connessione, scatto_la, mare_la) == "no"
    assert esito.etichette_perse == 1


def test_un_nodo_cestinato_di_la_ma_usato_di_qua_resta(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    _travaso(fisso, zen, tmp_path, "primo")

    nodi.cambia_stato(fisso.connessione, mare, "cestino")
    fisso.connessione.execute(
        "UPDATE cambiamenti SET avvenuto_il = '2020-01-01T00:00:00Z' "
        "WHERE azione = 'stato'")

    scatto_la = uno(zen.connessione, "SELECT id FROM scatti")["id"]
    mare_la = fusione.nodo_al_sentiero(zen.connessione, "mare")
    etichette.metti(zen.connessione, scatto_la, mare_la, "si", "utente")

    esito, _ = _travaso(fisso, zen, tmp_path, "secondo")

    riga = uno(zen.connessione, "SELECT stato FROM nodi WHERE id = ?", mare_la)
    assert riga["stato"] == "attivo"
    assert esito.nodi_risorti == 1
    assert esito.note


def test_un_nodo_cestinato_di_la_e_non_usato_qui_si_cestina(due_pc):
    fisso, zen, tmp_path = due_pc
    mare = nodi.crea(fisso.connessione, "mare")
    _travaso(fisso, zen, tmp_path, "primo")
    nodi.cambia_stato(fisso.connessione, mare, "cestino")
    esito, _ = _travaso(fisso, zen, tmp_path, "secondo")

    mare_la = fusione.nodo_al_sentiero(zen.connessione, "mare")
    riga = uno(zen.connessione, "SELECT stato FROM nodi WHERE id = ?", mare_la)
    assert riga["stato"] == "cestino"
    assert esito.nodi_cestinati == 1


def test_un_pacchetto_dal_futuro_non_si_fonde(due_pc):
    fisso, zen, tmp_path = due_pc
    nodi.crea(fisso.connessione, "mare")
    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)

    carta = formato.Carta.leggi(fatto.cartella)
    carta.fatto_il = "2099-01-01T00:00:00Z"
    carta.scrivi(fatto.cartella)

    with pytest.raises(ErroreOfficina) as guaio:
        fusione.fondi(zen, fatto.cartella, PAROLA)
    assert guaio.value.codice == "orologi_lontani"
    assert uno(zen.connessione, "SELECT count(*) AS c FROM nodi")["c"] == 0


def test_un_pacchetto_vecchio_si_fonde_lo_stesso(due_pc):
    fisso, zen, tmp_path = due_pc
    nodi.crea(fisso.connessione, "mare")
    fatto = costruzione.costruisci(fisso, tmp_path / "scambio", PAROLA)
    carta = formato.Carta.leggi(fatto.cartella)
    carta.fatto_il = "2020-01-01T00:00:00Z"
    carta.scrivi(fatto.cartella)

    esito = fusione.fondi(zen, fatto.cartella, PAROLA)
    assert esito.gesti_applicati == 1


def test_le_impronte_arrivano_gia_calcolate(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    inserisci(
        fisso.connessione,
        "INSERT INTO impronte (scatto_id, descrittore, versione, inquadratura, "
        "metodo, fotogramma, dimensione, valori, calcolata_il) "
        "VALUES (1, 'clip', 'v1', 'intera', 'intera', 0, 4, ?, ?)",
        b"\x00\x01\x02\x03", adesso())

    esito, _ = _travaso(fisso, zen, tmp_path)

    assert esito.impronte_prese == 1
    riga = uno(zen.connessione, "SELECT valori, descrittore FROM impronte")
    assert riga["valori"] == b"\x00\x01\x02\x03"
    assert riga["descrittore"] == "clip"


def test_cio_che_ricevo_non_finisce_nel_mio_registro(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, 1, mare, "si", "utente")

    _travaso(fisso, zen, tmp_path)

    assert cambiamenti.quanti_da_mandare(zen.connessione) == 0


def test_dopo_la_fusione_so_fin_dove_ho_letto(due_pc):
    fisso, zen, tmp_path = due_pc
    _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 50)
    nodi.crea(fisso.connessione, "mare")
    esito, fatto = _travaso(fisso, zen, tmp_path)

    altra = cambiamenti.altre_macchine(zen.connessione)[0]
    assert altra["visto_fino_a"] == fatto.carta.al_seriale
    assert altra["nome"] == fatto.carta.mittente_nome
