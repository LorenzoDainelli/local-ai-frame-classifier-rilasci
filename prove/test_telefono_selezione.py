from __future__ import annotations

import sqlite3

import pytest

from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.telefono import cifratura, dati, selezione


@pytest.fixture
def piena(archivio_misurabile):
    return archivio_misurabile


def _un_nodo(connessione) -> int:
    riga = uno(connessione,
               "SELECT nodo_id FROM etichette WHERE stato = 'si' "
               "GROUP BY nodo_id ORDER BY count(*) DESC LIMIT 1")
    assert riga, "l'archivio finto dovrebbe avere etichette"
    return riga["nodo_id"]


def test_di_partenza_entra_tutto(piena):
    connessione = piena.connessione
    scelti = selezione.numeri(connessione, selezione.Selezione())
    tutti_gli_scatti = uno(
        connessione,
        "SELECT count(*) AS quanti FROM scatti "
        "WHERE fuori_archivio = 0 AND sembra_schermata = 0")["quanti"]
    assert len(scelti) == tutti_gli_scatti > 0
    assert selezione.Selezione().e_tutto
    assert selezione.Selezione().a_parole() == "tutto l'archivio"


@pytest.mark.parametrize("scelta, detto", [
    (selezione.Selezione(nodi_esclusi=[3]), "tranne 1 ramo"),
    (selezione.Selezione(nodi_esclusi=[3, 4]), "tranne 2 rami"),
    (selezione.Selezione(nodi=[1]), "1 ramo dell'albero"),
    (selezione.Selezione(nodi=[1, 2]), "2 rami dell'albero"),
    (selezione.Selezione(persone=[1]), "con 1 persona"),
    (selezione.Selezione(persone=[1, 2]), "con 2 persone"),
    (selezione.Selezione(persone_escluse=[1]), "senza 1 persona"),
    (selezione.Selezione(persone_escluse=[1, 2]), "senza 2 persone"),
])
def test_la_selezione_si_dice_in_italiano(scelta, detto):
    assert detto in scelta.a_parole()


def test_le_schermate_e_il_fuori_archivio_non_entrano_mai(piena):
    connessione = piena.connessione
    scatto = tutti(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 2")
    with piena.scrittura() as scrivi:
        scrivi.execute("UPDATE scatti SET fuori_archivio = 1 WHERE id = ?",
                       (scatto[0]["id"],))
        scrivi.execute("UPDATE scatti SET sembra_schermata = 1 WHERE id = ?",
                       (scatto[1]["id"],))
    scelti = selezione.numeri(connessione, selezione.Selezione())
    assert scatto[0]["id"] not in scelti
    assert scatto[1]["id"] not in scelti


def test_i_video_non_hanno_interruttore():
    campi = set(selezione.Selezione.__dataclass_fields__)
    assert not {c for c in campi if "video" in c}


def test_un_nodo_scelto_porta_il_suo_ramo(piena):
    connessione = piena.connessione
    radice = uno(connessione,
                 "SELECT id FROM nodi WHERE genitore_id IS NULL LIMIT 1")["id"]
    col_ramo = selezione.numeri(connessione,
                                selezione.Selezione(nodi=[radice]))
    tutto = selezione.numeri(connessione, selezione.Selezione())
    etichettati = uno(
        connessione,
        "SELECT count(DISTINCT e.scatto_id) AS quanti FROM etichette e "
        "JOIN scatti s ON s.id = e.scatto_id WHERE e.stato = 'si' "
        "AND s.fuori_archivio = 0 AND s.sembra_schermata = 0")["quanti"]
    assert 0 < len(col_ramo) <= len(tutto)
    assert len(col_ramo) == etichettati


def test_un_nodo_escluso_toglie_il_suo_ramo(piena):
    connessione = piena.connessione
    nodo = _un_nodo(connessione)
    con = set(selezione.numeri(connessione, selezione.Selezione(nodi=[nodo])))
    senza = set(selezione.numeri(connessione,
                                 selezione.Selezione(nodi_esclusi=[nodo])))
    assert con and senza
    assert not (con & senza)


def test_il_periodo_stringe(piena):
    connessione = piena.connessione
    meta = uno(connessione,
               "SELECT giorno FROM scatti WHERE giorno IS NOT NULL "
               "ORDER BY giorno LIMIT 1 OFFSET 3")["giorno"]
    dopo = selezione.numeri(connessione,
                            selezione.Selezione(dal_giorno=meta))
    prima = selezione.numeri(connessione,
                             selezione.Selezione(al_giorno=meta))
    assert dopo and prima
    for scatto_id in dopo:
        riga = uno(connessione, "SELECT giorno FROM scatti WHERE id = ?",
                   scatto_id)
        assert riga["giorno"] and riga["giorno"] >= meta


def test_un_periodo_lascia_fuori_i_senza_data(piena):
    connessione = piena.connessione
    senza_data = uno(connessione,
                     "SELECT count(*) AS quanti FROM scatti "
                     "WHERE giorno IS NULL AND fuori_archivio = 0 "
                     "AND sembra_schermata = 0")["quanti"]
    assert senza_data > 0, "l'archivio finto ha degli scatti senza data"
    scelti = selezione.numeri(connessione,
                              selezione.Selezione(dal_giorno="1900-01-01"))
    for scatto_id in scelti:
        assert uno(connessione, "SELECT giorno FROM scatti WHERE id = ?",
                   scatto_id)["giorno"] is not None


def test_tutto_tranne_le_foto_di_una_persona(piena):
    connessione = piena.connessione
    qualcuno = tutti(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 3")
    with piena.scrittura() as scrivi:
        persona = scrivi.execute(
            "INSERT INTO persone (nome, stato, nata_il) "
            "VALUES ('Anna', 'attiva', '2026-01-01T00:00:00Z')").lastrowid
        for riga in qualcuno:
            scrivi.execute(
                "INSERT INTO persone_negli_scatti (scatto_id, persona_id, "
                "messa_il) VALUES (?, ?, '2026-01-01T00:00:00Z')",
                (riga["id"], persona))

    con = selezione.numeri(connessione,
                           selezione.Selezione(persone=[persona]))
    senza = selezione.numeri(connessione,
                             selezione.Selezione(persone_escluse=[persona]))
    assert sorted(con) == sorted(r["id"] for r in qualcuno)
    assert not set(con) & set(senza)
    assert len(senza) == len(selezione.numeri(
        connessione, selezione.Selezione())) - len(con)


def test_la_selezione_si_salva_e_si_rilegge():
    scelta = selezione.Selezione(nodi=[3, 4], persone_escluse=[7],
                                 dal_giorno="2019-01-01")
    riletta = selezione.Selezione.da_json(scelta.a_json())
    assert riletta == scelta


def test_una_selezione_di_domani_non_fa_saltare_niente():
    riletta = selezione.Selezione.da_json(
        '{"nodi": [2], "colore_preferito": "blu"}')
    assert riletta.nodi == [2]
    assert selezione.Selezione.da_json("non è json").e_tutto
    assert selezione.Selezione.da_json(None).e_tutto


def test_la_stima_non_e_una_stima(piena):
    connessione = piena.connessione
    conto = selezione.stima(connessione, selezione.Selezione())

    atteso = 0
    for riga in tutti(connessione,
                      "SELECT f.dimensione FROM file_media f "
                      "JOIN scatti s ON s.id = f.scatto_id "
                      "WHERE s.fuori_archivio = 0 AND s.sembra_schermata = 0 "
                      "AND EXISTS (SELECT 1 FROM percorsi p "
                      "            WHERE p.file_id = f.id AND p.presente = 1)"):
        atteso += cifratura.peso_cifrato(riga["dimensione"])
    assert conto.peso_originali == atteso
    assert conto.peso > conto.peso_originali
    assert conto.quanti_scatti > 0
    assert conto.dal_giorno and conto.al_giorno


def test_la_stima_scende_quando_si_stringe(piena):
    connessione = piena.connessione
    nodo = _un_nodo(connessione)
    tutto = selezione.stima(connessione, selezione.Selezione())
    meno = selezione.stima(connessione, selezione.Selezione(nodi=[nodo]))
    assert meno.peso < tutto.peso
    assert meno.quanti_scatti < tutto.quanti_scatti


def test_le_live_photo_contano_due_file(piena):
    connessione = piena.connessione
    conto = selezione.stima(connessione, selezione.Selezione())
    quante_live = uno(connessione,
                      "SELECT count(*) AS quante FROM scatti "
                      "WHERE genere = 'live' AND fuori_archivio = 0")["quante"]
    assert quante_live > 0
    assert conto.quanti_file >= conto.quanti_scatti + quante_live - \
        conto.file_mancanti


def test_lo_spazio_che_non_si_sa_non_e_un_si():
    conto = selezione.Stima(peso_originali=10)
    assert conto.ci_sta_in(None) is None
    assert conto.ci_sta_in(0) is None
    assert conto.ci_sta_in(1_000_000) is True
    assert conto.ci_sta_in(5) is False


def test_il_tasto_dice_cosa_fa():
    conto = selezione.Stima(quanti_scatti=28_740, peso_originali=41 * 10 ** 9)
    detto = conto.sul_tasto("iPhone")
    assert detto.startswith("Prepara 28.740 scatti")
    assert "iPhone" in detto and "GB" in detto


def test_i_numeri_si_dicono_in_italiano():
    assert selezione.a_numero(28_740) == "28.740"
    assert selezione.a_misura(41 * 10 ** 9) == "41,0 GB"
    assert selezione.a_misura(500) == "500 byte"


def test_un_telefono_ha_un_nome_solo(piena):
    with piena.scrittura() as connessione:
        telefoni.crea(connessione, "iPhone", "ios")
        with pytest.raises(ErroreOfficina):
            telefoni.crea(connessione, "iPhone", "ios")
        with pytest.raises(ErroreOfficina):
            telefoni.crea(connessione, "   ")


def test_il_pc_si_ricorda_la_selezione(piena):
    scelta = selezione.Selezione(dal_giorno="2020-01-01", persone_escluse=[9])
    with piena.scrittura() as connessione:
        telefono = telefoni.crea(connessione, "Redmi", "android")
        telefoni.salva_selezione(connessione, telefono, scelta.a_json())
    riga = telefoni.per_id(piena.connessione, telefono)
    assert selezione.Selezione.da_json(riga["selezione"]) == scelta


def test_due_telefoni_non_si_toccano(piena):
    with piena.scrittura() as connessione:
        uno_id = telefoni.crea(connessione, "iPhone", "ios")
        altro_id = telefoni.crea(connessione, "Redmi", "android")
        telefoni.salva_selezione(
            connessione, uno_id, selezione.Selezione(nodi=[1]).a_json())
        telefoni.segna_file(connessione, uno_id, "foto/2019/07/a.heic",
                            "originale", "a" * 64, 100, 200, 1)
    assert telefoni.dentro_il_pacchetto(piena.connessione, altro_id) == {}
    assert telefoni.peso_del_pacchetto(piena.connessione, altro_id) == (0, 0)
    assert telefoni.peso_del_pacchetto(piena.connessione, uno_id) == (1, 200)


def test_il_registro_dei_travasi_si_chiude(piena):
    with piena.scrittura() as connessione:
        telefono = telefoni.crea(connessione, "iPhone", "ios")
        travaso = telefoni.apri_travaso(connessione, telefono, "D:/Visore", 120)
        assert telefoni.travaso_lasciato_a_meta(connessione, telefono)
        telefoni.aggiorna_travaso(connessione, travaso, scritti=50, peso=999)
        telefoni.chiudi_travaso(connessione, travaso)
    connessione = piena.connessione
    assert telefoni.travaso_lasciato_a_meta(connessione, telefono) is None
    ultimo = telefoni.ultimi_travasi(connessione, telefono)[0]
    assert ultimo["scritti"] == 50 and ultimo["stato"] == "finito"
    assert telefoni.per_id(connessione, telefono)["ultimo_travaso_il"]


def test_l_identificativo_dell_archivio_e_stabile_e_muto(piena):
    with piena.scrittura() as connessione:
        primo = telefoni.identificativo(connessione)
        secondo = telefoni.identificativo(connessione)
    assert primo == secondo
    assert len(primo) == 16
    assert all(c in "0123456789abcdef" for c in primo)


def _costruisci(piena, quanti=None):
    connessione = piena.connessione
    scelti = selezione.numeri(connessione, selezione.Selezione())
    if quanti:
        scelti = scelti[:quanti]
    posti = []
    for numero, scatto_id in enumerate(scelti):
        riga = uno(connessione,
                   "SELECT impronta, dimensione FROM file_media "
                   "WHERE scatto_id = ? ORDER BY ruolo LIMIT 1", scatto_id)
        posti.append(dati.Posto(
            scatto_id=scatto_id, impronta=riga["impronta"],
            posto=f"foto/2019/07/f{numero}.jpg",
            dimensione=riga["dimensione"],
            mini=f"mini/aa/{riga['impronta']}.jpg"))
    grezzo = dati.costruisci(connessione, posti, {},
                             {"versione_officina": "0.5.0"},
                             piena.dove.radice / "lavoro")
    return grezzo, posti


def _apri(tmp_path, grezzo: bytes) -> sqlite3.Connection:
    percorso = tmp_path / "dati.db"
    percorso.write_bytes(grezzo)
    fuori = sqlite3.connect(percorso)
    fuori.row_factory = sqlite3.Row
    return fuori


def test_il_database_del_telefono_si_apre_e_ha_tutto(piena, tmp_path):
    grezzo, posti = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    quanti = uno(dentro, "SELECT count(*) AS quanti FROM scatti")["quanti"]
    assert quanti == len(posti)
    assert uno(dentro, "SELECT count(*) AS quanti FROM nodi")["quanti"] > 0
    assert uno(dentro, "SELECT valore FROM informazioni "
                       "WHERE chiave = 'versione_officina'")["valore"] == "0.5.0"


def test_ogni_scatto_porta_la_sua_impronta_non_solo_il_numero(piena, tmp_path):
    grezzo, posti = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    impronte = {r["impronta"] for r in tutti(dentro, "SELECT impronta FROM scatti")}
    assert impronte == {p.impronta for p in posti}
    assert all(len(x) == 64 for x in impronte)


def test_i_nodi_senza_foto_nel_pacchetto_non_compaiono(piena, tmp_path):
    with piena.scrittura() as connessione:
        vuoto = connessione.execute(
            "INSERT INTO nodi (nome, stato, creato_il) "
            "VALUES ('nodo_vuoto', 'attivo', '2026-01-01T00:00:00Z')").lastrowid
    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    assert uno(dentro, "SELECT id FROM nodi WHERE id = ?", vuoto) is None


def test_il_conto_col_ramo_non_conta_due_volte(piena, tmp_path):
    connessione = piena.connessione
    figlio = _un_nodo(connessione)
    padre = uno(connessione, "SELECT genitore_id FROM nodi WHERE id = ?",
                figlio)["genitore_id"]
    assert padre, "il ramo di prova ha una radice"
    scatto = uno(connessione,
                 "SELECT scatto_id FROM etichette WHERE nodo_id = ? LIMIT 1",
                 figlio)["scatto_id"]
    with piena.scrittura() as scrivi:
        scrivi.execute(
            "INSERT OR IGNORE INTO etichette (scatto_id, nodo_id, stato, "
            "origine, creata_il) VALUES (?, ?, 'si', 'utente', "
            "'2026-01-01T00:00:00Z')", (scatto, padre))

    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    riga = uno(dentro, "SELECT quanti, quanti_col_ramo FROM nodi WHERE id = ?",
               padre)
    scatti_veri = uno(dentro,
                      "SELECT count(DISTINCT e.scatto_id) AS quanti "
                      "FROM etichette e JOIN nodi n ON n.id = e.nodo_id "
                      "WHERE n.id = ? OR n.genitore_id = ?",
                      padre, padre)["quanti"]
    assert riga["quanti"] == 1
    assert riga["quanti_col_ramo"] == scatti_veri


def test_le_persone_senza_nome_non_entrano(piena, tmp_path):
    scatti = tutti(piena.connessione, "SELECT id FROM scatti ORDER BY id LIMIT 4")
    with piena.scrittura() as scrivi:
        con_nome = scrivi.execute(
            "INSERT INTO persone (nome, stato, nata_il) "
            "VALUES ('Anna', 'attiva', '2026-01-01T00:00:00Z')").lastrowid
        anonima = scrivi.execute(
            "INSERT INTO persone (nome, stato, nata_il) "
            "VALUES (NULL, 'attiva', '2026-01-01T00:00:00Z')").lastrowid
        for riga in scatti:
            for persona in (con_nome, anonima):
                scrivi.execute(
                    "INSERT INTO persone_negli_scatti (scatto_id, persona_id, "
                    "messa_il) VALUES (?, ?, '2026-01-01T00:00:00Z')",
                    (riga["id"], persona))

    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    nomi = [r["nome"] for r in tutti(dentro, "SELECT nome FROM persone")]
    assert nomi == ["Anna"]
    assert uno(dentro, "SELECT quanti FROM persone WHERE id = ?",
               con_nome)["quanti"] == len(scatti)
    assert uno(dentro, "SELECT count(*) AS quanti FROM persone_negli_scatti "
                       "WHERE persona_id = ?", anonima)["quanti"] == 0


def test_spesso_insieme_a_conta_le_foto_in_comune(piena, tmp_path):
    scatti = [r["id"] for r in tutti(piena.connessione,
                                     "SELECT id FROM scatti ORDER BY id LIMIT 5")]
    with piena.scrittura() as scrivi:
        anna = scrivi.execute(
            "INSERT INTO persone (nome, stato, nata_il) "
            "VALUES ('Anna', 'attiva', '2026-01-01T00:00:00Z')").lastrowid
        marco = scrivi.execute(
            "INSERT INTO persone (nome, stato, nata_il) "
            "VALUES ('Marco', 'attiva', '2026-01-01T00:00:00Z')").lastrowid
        for scatto in scatti:
            scrivi.execute(
                "INSERT INTO persone_negli_scatti (scatto_id, persona_id, "
                "messa_il) VALUES (?, ?, '2026-01-01T00:00:00Z')",
                (scatto, anna))
        for scatto in scatti[:3]:
            scrivi.execute(
                "INSERT INTO persone_negli_scatti (scatto_id, persona_id, "
                "messa_il) VALUES (?, ?, '2026-01-01T00:00:00Z')",
                (scatto, marco))

    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    riga = uno(dentro, "SELECT quante FROM insieme WHERE persona_id = ? "
                       "AND altra_id = ?", anna, marco)
    assert riga["quante"] == 3


def test_le_impronte_dei_volti_non_escono(piena, tmp_path):
    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    tabelle = {r["name"] for r in tutti(
        dentro, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "volti" not in tabelle
    colonne = {r["name"] for r in tutti(dentro, "PRAGMA table_info(persone)")}
    assert "impronta" not in colonne
    assert b"impronta_volto" not in grezzo


def test_le_due_tabelle_che_nascono_vuote_ci_sono_lo_stesso(piena, tmp_path):
    grezzo, _ = _costruisci(piena)
    dentro = _apri(tmp_path, grezzo)
    for tabella in ("parole", "filtri", "cuori", "cuori_tolti", "raccolte"):
        assert uno(dentro,
                   f"SELECT count(*) AS quanti FROM {tabella}")["quanti"] == 0


def test_il_file_di_lavoro_non_resta_in_giro(piena):
    lavoro = piena.dove.radice / "lavoro"
    _costruisci(piena, quanti=3)
    assert not list(lavoro.glob("*.sqlite"))
