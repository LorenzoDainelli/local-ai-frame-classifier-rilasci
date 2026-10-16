from __future__ import annotations

from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.importazione import raccolta, storico


@pytest.fixture
def mandata(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        return storico.mandate(connessione)[0]


def _percorsi_veri(archivio) -> list[Path]:
    from officina.archivio.database import tutti

    with archivio.lettura() as connessione:
        return [Path(r["percorso"]) for r in tutti(
            connessione, "SELECT percorso FROM percorsi WHERE presente = 1")]


def test_gli_originali_restano_dove_erano(archivio_pieno, mandata, tmp_path):
    prima = {p: p.stat().st_size for p in _percorsi_veri(archivio_pieno)
             if p.exists()}
    assert prima, "nessun file vero: la prova non sta guardando niente"

    dove = tmp_path / "Le mie importazioni"
    with archivio_pieno.lettura() as connessione:
        raccolta.raccogli(connessione, mandata.id, mandata.come_si_chiama, dove)

    dopo = {p: p.stat().st_size for p in prima if p.exists()}
    assert dopo == prima, (
        "un originale si è mosso o è cambiato: la copia si è comportata "
        "come uno spostamento")


def test_la_cartella_si_riempie(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "Le mie importazioni"
    with archivio_pieno.lettura() as connessione:
        esito = raccolta.raccogli(connessione, mandata.id,
                                  mandata.come_si_chiama, dove)
    dentro = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    assert esito.copiati > 0
    assert not esito.guasti
    assert len(list(dentro.iterdir())) == esito.copiati
    assert not list(dentro.glob("*.parziale")), (
        "è rimasto un file a metà: allora un'interruzione lascerebbe in giro "
        "spazzatura che sembra una fotografia")


def test_non_si_copia_dentro_una_cartella_sorgente(archivio_pieno, tmp_path):
    from officina.archivio.database import uno

    with archivio_pieno.lettura() as connessione:
        sorgente = Path(uno(connessione,
                            "SELECT percorso FROM cartelle_sorgente")["percorso"])

        with pytest.raises(ErroreOfficina):
            raccolta.controlla_destinazione(connessione, sorgente)
        with pytest.raises(ErroreOfficina):
            raccolta.controlla_destinazione(connessione, sorgente / "copie")
        with pytest.raises(ErroreOfficina):
            raccolta.controlla_destinazione(connessione, sorgente.parent)

        raccolta.controlla_destinazione(connessione, tmp_path / "altrove")


def test_un_percorso_a_meta_non_si_accetta(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        with pytest.raises(ErroreOfficina):
            raccolta.controlla_destinazione(connessione, Path("foto"))


def test_rifarla_non_ricopia_niente(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    with archivio_pieno.lettura() as connessione:
        primo = raccolta.raccogli(connessione, mandata.id,
                                  mandata.come_si_chiama, dove)
        secondo = raccolta.raccogli(connessione, mandata.id,
                                    mandata.come_si_chiama, dove)
    assert primo.copiati > 0 and primo.saltati == 0
    assert secondo.copiati == 0
    assert secondo.saltati == primo.copiati


def test_il_piano_dice_quanto_manca(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    with archivio_pieno.lettura() as connessione:
        prima = raccolta.prepara(connessione, mandata.id,
                                 mandata.come_si_chiama, dove)
        assert prima.quanti > 0
        assert prima.gia_fatti == 0
        assert prima.da_copiare == prima.quanti
        assert prima.byte > 0

        raccolta.raccogli(connessione, mandata.id, mandata.come_si_chiama, dove)

        dopo = raccolta.prepara(connessione, mandata.id,
                                mandata.come_si_chiama, dove)
    assert dopo.quanti == prima.quanti
    assert dopo.da_copiare == 0
    assert dopo.byte == 0, "dice che c'è ancora da scrivere, e non c'è più"


def test_si_puo_fermare_a_meta(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    quanti = []

    def basta():
        quanti.append(1)
        return len(quanti) > 2

    with archivio_pieno.lettura() as connessione:
        esito = raccolta.raccogli(connessione, mandata.id,
                                  mandata.come_si_chiama, dove, fermati=basta)
        resto = raccolta.raccogli(connessione, mandata.id,
                                  mandata.come_si_chiama, dove)
    assert esito.copiati == 2
    assert resto.saltati == 2


def test_due_file_con_lo_stesso_nome_non_si_sovrascrivono():
    presi: dict[str, str] = {}
    uno = {"nome": "IMG_0001.JPG", "impronta": "aaaaaaaaaaaa"}
    due = {"nome": "IMG_0001.JPG", "impronta": "bbbbbbbbbbbb"}
    primo = raccolta._come_si_chiamera(uno, presi)
    secondo = raccolta._come_si_chiamera(due, presi)
    assert primo == "IMG_0001.JPG"
    assert secondo != primo
    assert secondo.endswith(".JPG"), "il secondo ha perso l'estensione"

    ancora: dict[str, str] = {}
    assert raccolta._come_si_chiamera(uno, ancora) == primo
    assert raccolta._come_si_chiamera(due, ancora) == secondo


def test_lo_stesso_file_due_volte_resta_un_nome_solo():
    presi: dict[str, str] = {}
    riga = {"nome": "a.jpg", "impronta": "cccccccccccc"}
    assert raccolta._come_si_chiamera(riga, presi) == "a.jpg"
    assert raccolta._come_si_chiamera(riga, presi) == "a.jpg"


def test_i_nomi_che_windows_non_vuole():
    assert raccolta.nome_cartella(3, "Foto: vacanze?") == "Importazione 3 - Foto vacanze"
    assert raccolta.nome_cartella(7, None) == "Importazione 7"
    assert raccolta.nome_cartella(1, "///") == "Importazione 1", (
        "un nome fatto solo di caratteri vietati lascia un trattino appeso")
    presi: dict[str, str] = {}
    assert "/" not in raccolta._come_si_chiamera(
        {"nome": "a/b.jpg", "impronta": "d" * 16}, presi)


def test_tutte_le_mandate_sotto_lo_stesso_tetto(archivio_pieno, tmp_path):
    dove = tmp_path / "Le mie importazioni"
    with archivio_pieno.lettura() as connessione:
        piano = raccolta.prepara_tutte(connessione, dove)
        esito = raccolta.raccogli_tutte(connessione, dove)
    assert piano.quanti > 0
    assert esito.copiati == piano.quanti
    cartelle = sorted(p.name for p in dove.iterdir() if p.is_dir())
    assert cartelle, "nessuna cartella creata"
    for nome in cartelle:
        assert nome.startswith("Importazione "), nome
        assert list((dove / nome).iterdir()), (
            f"«{nome}» è una cartella vuota col nome di una mandata: chi la "
            "trova si chiede cos'è")


def test_il_conto_di_tutte_dice_quello_che_manca(archivio_pieno, tmp_path):
    dove = tmp_path / "raccolta"
    with archivio_pieno.lettura() as connessione:
        prima = raccolta.prepara_tutte(connessione, dove)
        raccolta.raccogli_tutte(connessione, dove)
        dopo = raccolta.prepara_tutte(connessione, dove)
    assert prima.byte > 0 and prima.da_copiare > 0
    assert dopo.quanti == prima.quanti
    assert dopo.da_copiare == 0
    assert dopo.byte == 0


def test_lo_spazio_si_dice_prima(archivio_pieno, tmp_path, monkeypatch):
    dove = tmp_path / "raccolta"
    with archivio_pieno.lettura() as connessione:
        piano = raccolta.prepara_tutte(connessione, dove)
        assert piano.spazio_basta

        stretto = type(piano)(cartella=piano.cartella, quanti=piano.quanti,
                              byte=piano.byte, liberi=0)
        assert not stretto.spazio_basta


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_non_si_copia_senza_aver_contato(cliente, tmp_path):
    from officina.web.strade import comune

    comune.piano_raccolta = None
    risposta = cliente.post("/raccolta/parti")
    assert risposta.status_code >= 400
    pagina = cliente.get("/importazione").text
    assert "/raccolta/parti" not in pagina


def test_contare_non_copia_niente(cliente, tmp_path, archivio_pieno):
    dove = tmp_path / "raccolta"
    risposta = cliente.post("/raccolta/conta", data={"dove": str(dove)},
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert not any(dove.glob("Importazione*")), (
        "contare ha copiato: allora non si può più ripensarci")

    pagina = cliente.get("/importazione").text
    assert "Da copiare" in pagina
    assert "/raccolta/parti" in pagina
    assert archivio_pieno.impostazione("cartella_raccolta") == str(dove)


def test_la_cartella_sbagliata_si_dice_subito(cliente, archivio_pieno):
    from officina.archivio.database import uno

    with archivio_pieno.lettura() as connessione:
        sorgente = uno(connessione,
                       "SELECT percorso FROM cartelle_sorgente")["percorso"]
    risposta = cliente.post("/raccolta/conta", data={"dove": sorgente})
    assert risposta.status_code >= 400
    assert "importerebbe" in risposta.text


def test_come_va_la_raccolta_si_puo_chiedere(cliente):
    dati = cliente.get("/api/raccolta").json()
    assert "finito" in dati and "righe" in dati


def test_un_nome_lunghissimo_non_fa_una_cartella_che_windows_rifiuta():
    nome = raccolta.nome_cartella(7, "vacanze " * 60 + ".")
    assert nome.startswith("Importazione 7 - vacanze")
    assert len(nome) <= len("Importazione 7 - ") + 80
    assert not nome.endswith((" ", "."))
