from __future__ import annotations

import sqlite3

from officina.programma import avvio, pagine


def _guasto() -> BaseException:
    try:
        try:
            prova = sqlite3.connect(":memory:")
            prova.execute("SELECT colonna_che_non_c_e FROM sqlite_master")
        except sqlite3.Error as errore:
            raise RuntimeError("C:\\Users\\qualcuno\\segreto") from errore
    except RuntimeError as guasto:
        return guasto


def test_il_dettaglio_per_claude_dice_il_database_ma_non_le_cartelle():
    testo = avvio._per_claude("9.9.9", _guasto())
    assert testo.startswith("Versione 9.9.9\nGuasto: RuntimeError")
    assert "Causato da: OperationalError" in testo
    assert "Database: no such column: colonna_che_non_c_e" in testo
    assert "qualcuno" not in testo and "segreto" not in testo


def test_un_guasto_del_disco_dice_solo_i_numeri():
    errore = OSError(13, "Accesso negato", "C:\\Users\\qualcuno\\archivio.sqlite")
    testo = avvio._per_claude("1", errore)
    assert "Disco: errno 13" in testo
    assert "qualcuno" not in testo and "Accesso negato" not in testo


def test_la_pagina_del_guasto_ha_il_tasto_copia_per_claude():
    pagina = pagine.attesa("Non sono riuscito ad aprire l'archivio", "detto", gira=False,
                           tecnico="Versione 1\nGuasto: X")
    assert 'id="copia-tecnico"' in pagina and "Guasto: X" in pagina
    senza = pagine.attesa("Titolo", "detto", gira=False)
    assert 'id="copia-tecnico"' not in senza
