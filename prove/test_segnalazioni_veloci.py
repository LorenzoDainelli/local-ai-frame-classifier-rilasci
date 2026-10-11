from __future__ import annotations

from officina.modello import segnalazioni


def test_saltare_gli_scatti_segnalati_non_scorre_tutte_le_segnalazioni(archivio):
    domanda = ("SELECT count(*) FROM scatti s WHERE s.fuori_archivio = 0"
               + segnalazioni.clausola(segnalazioni.NON_SI_APRE)
               + segnalazioni.clausola(segnalazioni.FIGURE_NON_FATTE))
    with archivio.lettura() as connessione:
        piano = [riga[3] for riga in connessione.execute("EXPLAIN QUERY PLAN " + domanda)]
    cerca = [passo for passo in piano if passo.startswith("SEARCH g")]
    assert len(cerca) == 2
    assert all("segnalazioni_per_scatto" in passo and "scatto_id=?" in passo for passo in cerca)


def test_nessun_indice_ripete_un_altro_indice(archivio):
    with archivio.lettura() as connessione:
        tavole = [r[0] for r in connessione.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        doppi = []
        for tavola in tavole:
            indici = [(r[1], tuple(c[2] for c in connessione.execute(f"PRAGMA index_info('{r[1]}')")))
                      for r in connessione.execute(f"PRAGMA index_list('{tavola}')") if not r[4]]
            for nome, colonne in indici:
                for altro, sue in indici:
                    if nome != altro and colonne == sue[:len(colonne)] and not nome.startswith("sqlite_"):
                        doppi.append(f"{tavola}.{nome} è già dentro {altro}")
    assert doppi == []
