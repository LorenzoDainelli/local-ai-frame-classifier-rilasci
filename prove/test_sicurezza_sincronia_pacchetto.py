from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, inserisci, uno
from officina.errori import ErroreOfficina
from officina.impostazioni import Posizione
from officina.modello import etichette, nodi
from officina.sincronia import costruzione, formato, fusione, lettore
from officina.web import sincronia as sincronia_web

PAROLA = "questa-e-una-password"


def _foto(archivio, cartella, nome, contenuto, nota=None):
    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.parent.mkdir(parents=True, exist_ok=True)
    sorgente.write_bytes(contenuto)
    impronta = hashlib.blake2b(contenuto, digest_size=32).hexdigest()
    scatto_id = inserisci(
        connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, nota, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?, ?)", nota, adesso())
    file_id = inserisci(
        connessione,
        "INSERT INTO file_media (impronta, dimensione, genere, formato, scatto_id, ruolo, "
        "aggiunto_il) VALUES (?, ?, 'immagine', 'jpeg', ?, 'principale', ?)",
        impronta, len(contenuto), scatto_id, adesso())
    inserisci(connessione,
              "INSERT INTO percorsi (file_id, percorso, nome, visto_il) VALUES (?, ?, ?, ?)",
              file_id, str(sorgente), nome, adesso())
    return impronta, scatto_id


@pytest.fixture
def due_pc(archivio, tmp_path):
    altro = Archivio(Posizione(tmp_path / "zenbook", "finto")).apri()
    try:
        yield archivio, altro, tmp_path
    finally:
        altro.chiudi(con_copia=False)


def _ritocca_la_carta(cartella, **cambi):
    dove = cartella / formato.CARTA
    carta = json.loads(dove.read_text(encoding="utf-8"))
    carta.update(cambi)
    dove.write_text(json.dumps(carta), encoding="utf-8")


def test_una_carta_ritoccata_non_fa_perdere_i_pacchetti_veri(due_pc):
    fisso, zen, tmp = due_pc
    _, scatto_id = _foto(fisso, tmp / "foto", "una.jpg", b"contenuto finto" * 50)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, scatto_id, mare, "si", "utente")
    primo = costruzione.costruisci(fisso, tmp / "scambio1", PAROLA)
    _ritocca_la_carta(primo.cartella, al_seriale=10 ** 9, visto_di_te=10 ** 9)

    with pytest.raises(ErroreOfficina) as guaio:
        fusione.fondi(zen, primo.cartella, PAROLA)
    assert guaio.value.codice == "carta_manomessa"
    riga = uno(zen.connessione, "SELECT count(*) AS c FROM macchine WHERE questa = 0")
    assert riga["c"] == 0

    montagna = nodi.crea(fisso.connessione, "montagna")
    etichette.metti(fisso.connessione, scatto_id, montagna, "si", "utente")
    secondo = costruzione.costruisci(fisso, tmp / "scambio2", PAROLA)
    esito = fusione.fondi(zen, secondo.cartella, PAROLA)
    assert esito.gesti_applicati >= 2
    assert fusione.nodo_al_sentiero(zen.connessione, "montagna") is not None


@pytest.mark.parametrize("cambio", [{"dal_seriale": 0, "al_seriale": 0},
                                    {"fatto_il": "2000-01-01T00:00:00Z"},
                                    {"mittente_codice": "0" * 32},
                                    {"archivio": "altro"}])
def test_ogni_campo_che_decide_e_garantito_dalla_cassaforte(due_pc, cambio):
    fisso, zen, tmp = due_pc
    _, scatto_id = _foto(fisso, tmp / "foto", "una.jpg", b"altro contenuto" * 50)
    nodo = nodi.crea(fisso.connessione, "a")
    etichette.metti(fisso.connessione, scatto_id, nodo, "si", "utente")
    fatto = costruzione.costruisci(fisso, tmp / "s", PAROLA)
    _ritocca_la_carta(fatto.cartella, **cambio)

    with pytest.raises(ErroreOfficina) as guaio:
        with lettore.apri(fatto.cartella, PAROLA):
            pass
    assert guaio.value.codice == "carta_manomessa"


def test_sulla_chiavetta_non_passa_mai_niente_in_chiaro(archivio, tmp_path):
    marcatore = b"NOTA-SEGRETA-DI-PROVA"
    nodo = b"Nonna-NODO-SEGRETO"
    _foto(archivio, tmp_path / "foto", "IMG_SEGRETA.jpg", b"x" * 4000,
          nota=marcatore.decode())
    nodi.crea(archivio.connessione, nodo.decode())
    visti: list[str] = []

    def guarda():
        for dove in (tmp_path / "chiavetta").rglob("*"):
            if dove.is_file():
                grezzo = dove.read_bytes()
                if marcatore in grezzo or nodo in grezzo or b"SQLite format" in grezzo:
                    visti.append(dove.name)

    costruzione.costruisci(archivio, tmp_path / "chiavetta", PAROLA,
                           avanzamento=lambda fatti, quanti: guarda())
    guarda()
    assert visti == []
    nomi = [dove.name for dove in (tmp_path / "chiavetta").rglob("*")]
    assert not any("IMG_SEGRETA" in nome or "chiaro" in nome for nome in nomi)


def test_i_nomi_dei_file_sulla_chiavetta_non_sono_le_impronte(archivio, tmp_path):
    impronta, _ = _foto(archivio, tmp_path / "foto", "una.jpg", b"y" * 3000)
    fatto = costruzione.costruisci(archivio, tmp_path / "chiavetta", PAROLA)
    nomi = " ".join(str(dove.relative_to(fatto.cartella))
                    for dove in fatto.cartella.rglob("*"))
    assert impronta not in nomi
    assert impronta[:12] not in nomi
    assert ".jpeg" not in nomi


def test_un_pacchetto_della_versione_di_prima_va_rifatto(due_pc):
    fisso, zen, tmp = due_pc
    nodi.crea(fisso.connessione, "mare")
    fatto = costruzione.costruisci(fisso, tmp / "s", PAROLA)
    _ritocca_la_carta(fatto.cartella, versione_formato=4)

    with pytest.raises(ErroreOfficina) as guaio:
        fusione.fondi(zen, fatto.cartella, PAROLA)
    assert guaio.value.codice == "formato_vecchio"
    elenco = sincronia_web.pacchetti_nella_cartella(str(tmp / "s"))
    assert elenco and elenco[0]["vecchio"] is True


@pytest.mark.parametrize("carta", [
    {"mittente_codice": 5, "mittente_nome": "x", "archivio": "finto", "sale": "00",
     "prova": "00"},
    {"mittente_codice": "a", "mittente_nome": "x", "archivio": "finto", "sale": "00",
     "prova": "00", "al_seriale": "molti"},
    ["non", "un", "dizionario"],
    {"mittente_nome": "manca il resto"},
])
def test_una_carta_rovinata_non_rompe_l_elenco(archivio, tmp_path, carta):
    buono = costruzione.costruisci(archivio, tmp_path / "scambio", PAROLA)
    rotto = tmp_path / "scambio" / "rotto"
    rotto.mkdir()
    (rotto / formato.CARTA).write_text(json.dumps(carta), encoding="utf-8")

    elenco = sincronia_web.pacchetti_nella_cartella(str(tmp_path / "scambio"))
    assert [voce["nome"] for voce in elenco] == [buono.cartella.name]
    with pytest.raises(ErroreOfficina) as guaio:
        formato.Carta.leggi(rotto)
    assert guaio.value.codice == "carta_rovinata"


def _riscrivi_il_database(cartella, cambia):
    carta = formato.Carta.leggi(cartella)
    chiave = carta.chiave(PAROLA)
    grezzo = chiave.leggi_tutto(cartella / formato.DATI, formato.DATI)
    memoria = sqlite3.connect(":memory:")
    memoria.deserialize(grezzo)
    cambia(memoria)
    memoria.commit()
    chiave.scrivi_byte(memoria.serialize(), cartella / formato.DATI, formato.DATI)
    memoria.close()


def test_un_impronta_o_un_formato_strani_non_escono_dalle_ricevute(due_pc):
    fisso, zen, tmp = due_pc
    _foto(fisso, tmp / "foto", "una.jpg", b"z" * 2000)
    fatto = costruzione.costruisci(fisso, tmp / "s", PAROLA)

    def cambia(memoria):
        memoria.execute("UPDATE file SET impronta = '../../fuori', formato = '../../x'")

    _riscrivi_il_database(fatto.cartella, cambia)
    esito = fusione.fondi(zen, fatto.cartella, PAROLA)
    assert esito.file_nuovi == 0
    assert any("impronta" in nota for nota in esito.note)
    assert not (zen.dove.ricevute.parent / "fuori").exists()
    assert not any(zen.dove.radice.parent.glob("fuori*"))


def test_un_formato_strano_diventa_dat(due_pc):
    fisso, zen, tmp = due_pc
    impronta, _ = _foto(fisso, tmp / "foto", "una.jpg", b"w" * 2000)
    fatto = costruzione.costruisci(fisso, tmp / "s", PAROLA)
    _riscrivi_il_database(
        fatto.cartella,
        lambda memoria: memoria.execute("UPDATE file SET formato = '../../x'"))

    esito = fusione.fondi(zen, fatto.cartella, PAROLA)
    assert esito.file_nuovi == 1
    arrivato = zen.dove.ricevute / impronta[:2] / f"{impronta}.dat"
    assert arrivato.is_file()


def test_lo_scrypt_della_sincronia_e_piu_caro(archivio, tmp_path):
    fatto = costruzione.costruisci(archivio, tmp_path / "s", PAROLA)
    carta = formato.Carta.leggi(fatto.cartella)
    assert carta.n == 2 ** 17
    assert carta.versione_formato == 5
