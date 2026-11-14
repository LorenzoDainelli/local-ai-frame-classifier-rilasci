from __future__ import annotations

from officina import ricerca
from officina.archivio.database import adesso
from officina.modello import nodi, posti, scatti


def _cerca(archivio, frase, **altro):
    return ricerca.cerca(archivio.connessione, archivio.dove.modelli, frase, **altro)


def _generi(connessione, numeri):
    if not numeri:
        return set()
    segni = ",".join("?" * len(numeri))
    return {r[0] for r in connessione.execute(
        f"SELECT genere FROM scatti WHERE id IN ({segni})", list(numeri))}


def test_trova_dal_nome_del_file(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT f.scatto_id, p.nome FROM percorsi p JOIN file_media f ON f.id = p.file_id "
        "WHERE p.nome LIKE 'IMG_1003%' LIMIT 1").fetchone()
    risposta = _cerca(archivio_misurabile, "img_1003")
    dal_nome = [t for t in risposta.trovati if t.sorgente == "nome"]
    assert [t.scatto_id for t in dal_nome] == [riga["scatto_id"]]
    assert any("nome del file" in d for d in risposta.detto)


def test_il_nome_non_prende_pezzi_troppo_corti(archivio_misurabile):
    risposta = _cerca(archivio_misurabile, "im")
    assert not [t for t in risposta.trovati if t.sorgente == "nome"]


def test_i_segni_speciali_del_nome_non_fanno_da_jolly(archivio_misurabile):
    risposta = _cerca(archivio_misurabile, "img%100")
    assert not [t for t in risposta.trovati if t.sorgente == "nome"]


def test_riconosce_un_luogo(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    luogo = posti.crea(connessione, "Lago Alto")
    scatto = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    connessione.execute(
        "INSERT INTO posti_negli_scatti (scatto_id, posto_id, messo_il) VALUES (?, ?, ?)",
        (scatto, luogo, adesso()))
    connessione.commit()
    risposta = _cerca(archivio_misurabile, "lago alto")
    assert [c.numero for c in risposta.capito if c.genere == "luogo"] == [luogo]
    assert [t.scatto_id for t in risposta.trovati if t.sorgente == "tua"] == [scatto]


def test_solo_un_filtro_li_da_tutti(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    risposta = _cerca(archivio_misurabile, "video", quanti=2, sicuri=ricerca.TUTTI)
    attesi = scatti.soli_numeri(connessione, scatti.Filtro(genere="video"))
    assert len(attesi) > 2
    assert sorted(t.scatto_id for t in risposta.trovati) == sorted(attesi)
    assert any("col filtro" in d for d in risposta.detto)
    assert not any("etichettati tu" in d for d in risposta.detto)


def test_foto_tiene_anche_le_live_ma_non_i_video(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    risposta = _cerca(archivio_misurabile, "solo foto", sicuri=ricerca.TUTTI)
    generi = _generi(connessione, [t.scatto_id for t in risposta.trovati])
    assert generi == {"foto", "live"}


def test_un_filtro_dentro_una_parola_non_conta(archivio_misurabile):
    risposta = _cerca(archivio_misurabile, "videogiochi")
    assert not [c for c in risposta.capito if c.genere == "filtro"]


def test_la_parola_foto_da_sola_non_toglie_i_video(archivio_misurabile):
    risposta = _cerca(archivio_misurabile, "foto al mare")
    assert not [c for c in risposta.capito if c.genere == "filtro"]


def test_il_filtro_restringe_un_nodo(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo = nodi.crea(connessione, "nodo_prova_filtri", None)
    tutti_gli_scatti = [r[0] for r in connessione.execute("SELECT id FROM scatti")]
    for numero in tutti_gli_scatti:
        connessione.execute(
            "INSERT OR IGNORE INTO etichette "
            "(scatto_id, nodo_id, stato, origine, creata_il) "
            "VALUES (?, ?, 'si', 'utente', ?)", (numero, nodo, adesso()))
    connessione.commit()
    risposta = _cerca(archivio_misurabile, "nodo_prova_filtri video",
                      sicuri=ricerca.TUTTI)
    assert risposta.trovati
    assert _generi(connessione, [t.scatto_id for t in risposta.trovati]) == {"video"}


def test_gli_fps_scritti_a_numero(archivio_misurabile):
    risposta = _cerca(archivio_misurabile, "120 fps")
    capiti = [c for c in risposta.capito if c.genere == "filtro"]
    assert [(c.chiave, c.valore) for c in capiti] == [("fps", "alti")]
    risposta = _cerca(archivio_misurabile, "30fps")
    capiti = [c for c in risposta.capito if c.genere == "filtro"]
    assert [(c.chiave, c.valore) for c in capiti] == [("fps", "ridotti")]


def test_le_parole_dei_filtri_portano_a_campi_veri():
    filtro = scatti.Filtro()
    for _parole, chiave, _valore in ricerca.PAROLE_DEI_FILTRI:
        assert hasattr(filtro, chiave), chiave
