from __future__ import annotations

from fastapi.testclient import TestClient

from officina import registro
from officina.impronte import perche
from officina.impronte.motore import Passata
from officina.modello import segnalazioni


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _foto(archivio, quante: int) -> list[int]:
    with archivio.lettura() as connessione:
        return [riga["id"] for riga in connessione.execute(
            "SELECT s.id FROM scatti s WHERE s.genere = 'foto' AND s.fuori_archivio = 0 "
            "ORDER BY s.id LIMIT ?", (quante,))]


def _togli_le_impronte(archivio, scatti: list[int]) -> None:
    with archivio.scrittura() as connessione:
        for scatto_id in scatti:
            connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto_id,))


def _sposta_il_file(archivio, scatto_id: int) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE percorsi SET percorso = percorso || '.sparito' WHERE file_id IN "
            "(SELECT id FROM file_media WHERE scatto_id = ?)", (scatto_id,))


def _ascolta(monkeypatch) -> list[tuple[str, dict]]:
    sentite = []
    monkeypatch.setattr(registro, "avviso",
                        lambda codice, **dati: sentite.append((codice, dati)))
    return sentite


def test_se_non_manca_niente_l_elenco_e_vuoto(archivio_misurabile):
    cosa = perche.guarda(archivio_misurabile)
    assert cosa["in_tutto"] == 0 and cosa["scatti"] == [] and cosa["modelli"]


def test_dice_chi_manca_e_cosa_succede_riaprendolo(archivio_misurabile):
    primo, secondo, terzo = _foto(archivio_misurabile, 3)
    _togli_le_impronte(archivio_misurabile, [primo, secondo, terzo])
    _sposta_il_file(archivio_misurabile, terzo)
    with archivio_misurabile.scrittura() as connessione:
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, secondo,
                           dettaglio="immagine_rovinata")
    cosa = perche.guarda(archivio_misurabile)
    assert cosa["in_tutto"] == 3
    voci = {voce["scatto"]: voce for voce in cosa["scatti"]}
    assert set(voci) == {primo, secondo, terzo}
    assert voci[primo]["da_parte"] is None
    assert voci[primo]["prova"]["esito"] == "si_apre"
    assert voci[primo]["prova"]["ritagli"] >= 1
    assert 0 <= voci[primo]["prova"]["luce"] <= 255
    assert voci[primo]["mancano"] == ["disegnato"] and voci[primo]["vecchie"] == 0
    assert voci[secondo]["da_parte"] == "immagine_rovinata"
    assert voci[secondo]["prova"]["esito"] == "si_apre"
    assert voci[terzo]["prova"]["esito"] == "saltato"
    assert voci[terzo]["prova"]["codice"]
    assert set(voci[primo]["lavori"]) == {"volti", "corpi", "scritte"}
    righe = cosa["testo"].splitlines()
    assert len(righe) == 4 and righe[0].startswith("Impronte: 3 scatti")
    assert f"scatto {secondo} |" in cosa["testo"]
    assert "da_parte=immagine_rovinata" in cosa["testo"]
    assert f"nome={voci[primo]['nome']}" in cosa["testo"] and voci[primo]["nome"]


def test_dice_se_gli_altri_lavori_lo_hanno_fatto(archivio_misurabile):
    [scatto] = _foto(archivio_misurabile, 1)
    _togli_le_impronte(archivio_misurabile, [scatto])
    with archivio_misurabile.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO volti_guardati (scatto_id, modello, versione, guardato_il) "
            "VALUES (?, 'm', '1', 'ora')", (scatto,))
        segnalazioni.segna(connessione, segnalazioni.CORPI_NON_LETTI, scatto)
    [voce] = perche.guarda(archivio_misurabile)["scatti"]
    assert voce["lavori"] == {"volti": "fatto", "corpi": "messo da parte",
                              "scritte": "non fatto"}


def test_un_guasto_imprevisto_dice_dove(archivio_misurabile, monkeypatch):
    [scatto] = _foto(archivio_misurabile, 1)
    _togli_le_impronte(archivio_misurabile, [scatto])

    def rotta(*_):
        raise ZeroDivisionError("x")

    monkeypatch.setattr(perche.lettura, "copia_di_lavoro", rotta)
    [voce] = perche.guarda(archivio_misurabile)["scatti"]
    assert voce["prova"]["esito"] == "rotto"
    assert voce["prova"]["guasto"] == "ZeroDivisionError"
    assert voce["prova"]["dove"] == "perche"
    assert "test_perche_mancano" in voce["prova"]["passi"]


def test_la_pagina_mostra_l_elenco_e_il_tasto(archivio_misurabile):
    [scatto] = _foto(archivio_misurabile, 1)
    _togli_le_impronte(archivio_misurabile, [scatto])
    pagina = _cliente().get("/intelligenza/perche-mancano")
    assert pagina.status_code == 200
    assert "Copia per Claude" in pagina.text
    assert f'href="/scatto/{scatto}"' in pagina.text
    assert 'href="/intelligenza/perche-mancano"' in _cliente().get("/intelligenza").text


def test_senza_mancanti_la_carta_non_ha_il_collegamento(archivio_misurabile):
    assert "perche-mancano" not in _cliente().get("/intelligenza").text
    assert "Non manca nessuna impronta" in _cliente().get(
        "/intelligenza/perche-mancano").text


def test_uno_scatto_saltato_lascia_una_riga_nel_registro(archivio_misurabile,
                                                         monkeypatch):
    [scatto] = _foto(archivio_misurabile, 1)
    _togli_le_impronte(archivio_misurabile, [scatto])
    _sposta_il_file(archivio_misurabile, scatto)
    sentite = _ascolta(monkeypatch)
    Passata(archivio_misurabile, "disegnato").esegui()
    saltati = [dati for codice, dati in sentite if codice == "impronte.scatto_saltato"]
    assert [dati["scatto"] for dati in saltati] == [scatto]
    assert isinstance(saltati[0]["motivo"], registro.Parola) and saltati[0]["motivo"]


def test_uno_scatto_senza_ritagli_lascia_una_riga_nel_registro(archivio_misurabile,
                                                              monkeypatch):
    primo, secondo = _foto(archivio_misurabile, 2)
    _togli_le_impronte(archivio_misurabile, [primo, secondo])
    vero = Passata._ritagli_di

    def senza(self, riga):
        return ([], 0) if riga["id"] == primo else vero(self, riga)

    monkeypatch.setattr(Passata, "_ritagli_di", senza)
    sentite = _ascolta(monkeypatch)
    Passata(archivio_misurabile, "disegnato").esegui()
    muti = [dati["scatto"] for codice, dati in sentite
            if codice == "impronte.scatto_senza_ritagli"]
    assert muti == [primo]
    with archivio_misurabile.lettura() as connessione:
        fatto = connessione.execute(
            "SELECT count(*) FROM impronte WHERE scatto_id = ?", (secondo,)).fetchone()[0]
    assert fatto > 0
