from __future__ import annotations

import time

from officina.archivio import database


def test_un_archivio_nuovo_non_ha_ancora_niente_da_imparare(archivio):
    with archivio.lettura() as connessione:
        assert database.non_ha_mai_guardato(connessione)


def test_dopo_un_importazione_le_statistiche_ci_sono(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        assert not database.non_ha_mai_guardato(connessione)
        righe = connessione.execute(
            "SELECT count(*) AS q FROM sqlite_stat1 WHERE tbl = 'scatti'"
        ).fetchone()
    assert righe["q"] > 0


def test_riaprendo_un_archivio_senza_statistiche_le_impara(archivio_pieno):
    from officina.archivio import accesso

    with archivio_pieno.scrittura() as connessione:
        connessione.execute("ANALYZE")
        connessione.execute("DROP TABLE IF EXISTS sqlite_stat1")
    with archivio_pieno.lettura() as connessione:
        assert database.non_ha_mai_guardato(connessione)

    dove = archivio_pieno.dove.nome
    accesso.chiudi(con_copia=False)
    riaperto = accesso.apri(dove)
    with riaperto.lettura() as connessione:
        assert not database.non_ha_mai_guardato(connessione)


def test_imparare_non_costa_piu_di_un_battito(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        partito = time.perf_counter()
        database.impara_com_e_fatto(connessione)
        quanto = (time.perf_counter() - partito) * 1000
    assert quanto < 2000, f"ANALYZE ha preso {quanto:.0f} millesimi"


def test_la_domanda_delle_mandate_usa_il_suo_indice(archivio_pieno):
    domanda = ("SELECT importazione_id, count(*) AS quanti FROM scatti "
               "WHERE fuori_archivio = 0 AND importazione_id IS NOT NULL "
               "GROUP BY importazione_id")
    with archivio_pieno.lettura() as connessione:
        connessione.execute("ANALYZE")
        piano = [riga["detail"] for riga in
                 connessione.execute("EXPLAIN QUERY PLAN " + domanda)]
    assert any("scatti_per_importazione" in passo for passo in piano), piano
