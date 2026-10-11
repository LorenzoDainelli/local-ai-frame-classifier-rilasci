from __future__ import annotations

from pathlib import Path

from officina.archivio.database import uno
from officina.impronte.motore import Passata
from officina.modello import file_media, segnalazioni


def _rompi_un_file(archivio, tmp_path: Path, byte: bytes = b"") -> tuple[int, Path]:
    with archivio.lettura() as connessione:
        riga = uno(connessione,
                   "SELECT p.id AS percorso_id, f.scatto_id "
                   "FROM percorsi p JOIN file_media f ON f.id = p.file_id "
                   "WHERE f.genere = 'immagine' AND f.scatto_id IS NOT NULL "
                   "ORDER BY p.id LIMIT 1")
    rotto = tmp_path / "rotto.jpg"
    rotto.write_bytes(byte)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE percorsi SET percorso = ? WHERE id = ?",
                            (str(rotto), riga["percorso_id"]))
    return riga["scatto_id"], rotto


def test_uno_scatto_che_non_si_apre_esce_dalla_coda(archivio_pieno, tmp_path):
    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)

    prima = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    prima.esegui()
    assert prima.avanzamento.saltati >= 1
    assert prima.avanzamento.messi_da_parte >= 1

    dopo = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    assert dopo.quanti_mancano() == 0


def test_lo_scatto_messo_da_parte_si_vede_col_suo_motivo(archivio_pieno, tmp_path):
    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()

    with archivio_pieno.lettura() as connessione:
        fuori = segnalazioni.non_si_aprono(connessione)

    assert [riga["scatto_id"] for riga in fuori] == [scatto_id]
    assert fuori[0]["dettaglio"] == "vuoto"


def test_due_passate_non_lasciano_due_segnalazioni(archivio_pieno, tmp_path):
    _rompi_un_file(archivio_pieno, tmp_path)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    with archivio_pieno.scrittura() as connessione:
        segnalazioni.riprova(connessione, segnalazioni.NON_SI_APRE)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()

    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.NON_SI_APRE) == 1


def test_rimetterlo_in_coda_lo_fa_riprovare(archivio_pieno, tmp_path):
    _rompi_un_file(archivio_pieno, tmp_path)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    assert Passata(archivio_pieno, "disegnato").quanti_mancano() == 0

    with archivio_pieno.scrittura() as connessione:
        assert segnalazioni.riprova(connessione, segnalazioni.NON_SI_APRE) == 1

    assert Passata(archivio_pieno, "disegnato").quanti_mancano() == 1


def test_se_ricopi_il_file_torna_in_coda_da_solo(archivio_pieno, tmp_path):
    _, rotto = _rompi_un_file(archivio_pieno, tmp_path)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    assert Passata(archivio_pieno, "disegnato").quanti_mancano() == 0

    rotto.write_bytes(b"adesso il file pesa qualcosa")
    with archivio_pieno.scrittura() as connessione:
        esito = file_media.controlla_presenza(connessione)

    assert esito["rimessi_in_coda"] == 1
    assert Passata(archivio_pieno, "disegnato").quanti_mancano() == 1


def test_un_file_sano_non_viene_rimesso_in_coda_per_niente(archivio_pieno):
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    with archivio_pieno.scrittura() as connessione:
        esito = file_media.controlla_presenza(connessione)

    assert esito["rimessi_in_coda"] == 0
    assert esito["spariti"] == 0


def test_anche_le_parole_smettono_di_riprovare(archivio_pieno, tmp_path):
    from officina.parole import SCHEDA
    from officina.parole import magazzino as parole_magazzino

    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)
    with archivio_pieno.scrittura() as connessione:
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                           dettaglio="vuoto")

    with archivio_pieno.lettura() as connessione:
        quanti = parole_magazzino.quanti_da_leggere(
            connessione, SCHEDA.nome, SCHEDA.versione)
        quali = parole_magazzino.da_leggere(
            connessione, SCHEDA.nome, SCHEDA.versione, quanti=500)

    assert scatto_id not in [riga["id"] for riga in quali]
    assert quanti == len(quali)


def test_anche_i_volti_saltano_quello_che_non_si_apre(archivio_pieno, tmp_path):
    from officina.volti import motore as volti_motore

    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)
    with archivio_pieno.scrittura() as connessione:
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                           dettaglio="vuoto")

    passata = volti_motore.Passata.__new__(volti_motore.Passata)
    domanda = volti_motore.Passata._domanda_da_fare(passata, "s.id")

    with archivio_pieno.lettura() as connessione:
        quali = [riga["id"] for riga in connessione.execute(
            domanda, ("un_modello", "1"))]

    assert scatto_id not in quali
    assert quali


def test_una_segnalazione_dei_volti_risolta_rimette_lo_scatto_in_coda(
        archivio_pieno):
    from officina.volti import motore as volti_motore

    with archivio_pieno.lettura() as connessione:
        primo = connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "ORDER BY id LIMIT 1").fetchone()["id"]

    passata = volti_motore.Passata.__new__(volti_motore.Passata)
    domanda = volti_motore.Passata._domanda_da_fare(passata, "s.id")

    with archivio_pieno.scrittura() as connessione:
        segnalazioni.segna(connessione, segnalazioni.VOLTI_NON_LETTI, primo,
                           dettaglio="niente facce")
    with archivio_pieno.lettura() as connessione:
        quali = [r["id"] for r in connessione.execute(domanda, ("m", "1"))]
    assert primo not in quali

    with archivio_pieno.scrittura() as connessione:
        segnalazioni.riprova(connessione, segnalazioni.VOLTI_NON_LETTI)
    with archivio_pieno.lettura() as connessione:
        quali = [r["id"] for r in connessione.execute(domanda, ("m", "1"))]
    assert primo in quali


def test_il_conto_della_barra_li_comprende(archivio_pieno, tmp_path):
    from officina.web.strade import base

    with archivio_pieno.lettura() as connessione:
        prima = base._conta_la_barra(connessione)["da_guardare"]

    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)
    with archivio_pieno.scrittura() as connessione:
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                           dettaglio="vuoto")

    with archivio_pieno.lettura() as connessione:
        dopo = base._conta_la_barra(connessione)["da_guardare"]

    assert dopo == prima + 1


def test_uno_scatto_che_si_rompe_in_modo_imprevisto_va_messo_da_parte(archivio_pieno, monkeypatch):
    from officina.impronte import motore

    with archivio_pieno.lettura() as connessione:
        scatto_id = uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
    vero = motore.Passata._ritagli_di

    def a_volte_si_rompe(self, riga):
        if riga["id"] == scatto_id:
            raise ValueError("dentro il file qualcosa non torna")
        return vero(self, riga)

    monkeypatch.setattr(motore.Passata, "_ritagli_di", a_volte_si_rompe)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    monkeypatch.undo()

    with archivio_pieno.lettura() as connessione:
        fuori = segnalazioni.non_si_aprono(connessione)
    assert [riga["scatto_id"] for riga in fuori] == [scatto_id]
    assert fuori[0]["dettaglio"] == "errore_imprevisto"
    assert fuori[0]["file_id"] is not None
    assert Passata(archivio_pieno, "disegnato").quanti_mancano() == 0


def test_togliere_dall_archivio_un_messo_da_parte_lo_toglie_anche_da_sistemare(archivio_pieno, tmp_path):
    from fastapi.testclient import TestClient

    from officina.web import server

    scatto_id, _ = _rompi_un_file(archivio_pieno, tmp_path)
    Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2).esegui()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    assert f"/elenchi/togli-messo-da-parte/{scatto_id}" in cliente.get("/sistemare").text

    cliente.post(f"/elenchi/togli-messo-da-parte/{scatto_id}")
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.NON_SI_APRE) == 0
        assert uno(connessione, "SELECT fuori_archivio FROM scatti WHERE id = ?",
                   scatto_id)["fuori_archivio"] == 1


def test_fermare_interrompe_un_video_a_meta(monkeypatch):
    import pytest

    from officina.immagini import fotogrammi

    def decodifica(percorso, lato=None, basta=None):
        assert basta()
        raise fotogrammi.Fermato()

    monkeypatch.setattr(fotogrammi, "_da_jpeg", lambda percorso: [])
    monkeypatch.setattr(fotogrammi, "c_e_il_decodificatore", lambda: True)
    monkeypatch.setattr(fotogrammi, "_da_decodificatore", decodifica)
    with pytest.raises(fotogrammi.Fermato):
        fotogrammi.prendi(Path(__file__), basta=lambda: True)
